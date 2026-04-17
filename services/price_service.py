"""
Price Service
Handles fetching and caching of stock prices and price changes from Bigdata API
"""

import os
import requests
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_BIGDATA_API_KEY = os.getenv("BIGDATA_API_KEY")
BIGDATA_BASE_URL = "https://api.bigdata.com/v1"
CACHE_TTL_MINUTES = 15  # 15 minute cache

# Price cache: {ticker: {price, change, currency, timestamp}}
price_cache: Dict[str, Dict] = {}


def _get_api_key(api_key: Optional[str] = None) -> str:
    """Get API key from parameter or fall back to default."""
    key = api_key or DEFAULT_BIGDATA_API_KEY
    if not key:
        raise ValueError("No Bigdata API key provided")
    return key


def format_timestamp(dt: datetime) -> str:
    """Format datetime to ISO 8601 with milliseconds and Z suffix"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    
    iso_str = dt.strftime('%Y-%m-%dT%H:%M:%S')
    milliseconds = dt.microsecond // 1000
    return f"{iso_str}.{milliseconds:03d}Z"


def is_cache_valid(cache_entry: Dict) -> bool:
    """Check if cache entry is still valid (within TTL)"""
    if "timestamp" not in cache_entry:
        return False
    
    age = datetime.now(timezone.utc) - cache_entry["timestamp"]
    return age < timedelta(minutes=CACHE_TTL_MINUTES)


def get_latest_price(entity_id: str, ticker: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """
    Fetch the latest/current price for a ticker.
    Uses 15-minute intervals to get the most recent price available.
    
    Args:
        entity_id: Bigdata entity ID
        ticker: Stock ticker symbol
        api_key: Optional API key (falls back to server default)
    
    Returns: {"price": float, "currency": str, "price_time": str} or None
    """
    try:
        key = _get_api_key(api_key)
        
        # Get current time and look back just 1 day for most recent data
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=1)
        
        # First try with 15-minute intervals for most current price
        response = requests.post(
            f"{BIGDATA_BASE_URL}/price/intraday/query",
            headers={
                "X-API-KEY": key,
                "Content-Type": "application/json"
            },
            json={
                "identifier": {
                    "type": "rp_entity_id",
                    "value": entity_id
                },
                "timestamp": {
                    "start": format_timestamp(start_time),
                    "end": format_timestamp(end_time)
                },
                "interval": "15min"  # Use 15-min intervals for more current data
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", {})
            
            # Check if we have values
            if results and "values" in results and results["values"]:
                values = results["values"]
                fields = results.get("fields", [])
                
                # Find indices for the fields we need
                try:
                    close_idx = fields.index("CLOSE")
                    currency_idx = fields.index("CURRENCY")
                    timestamp_idx = fields.index("TIMESTAMP") if "TIMESTAMP" in fields else 0
                    
                    # Values can be either:
                    # 1. A single array: [timestamp, open, low, high, close, volume, currency]
                    # 2. Multiple arrays: [[...], [...], ...]
                    if isinstance(values[0], list):
                        # Multiple data points - get the last (most recent) one
                        latest_values = values[-1]
                        close_price = latest_values[close_idx]
                        currency = latest_values[currency_idx]
                        price_time = latest_values[timestamp_idx] if timestamp_idx < len(latest_values) else None
                    else:
                        # Single data point
                        close_price = values[close_idx]
                        currency = values[currency_idx]
                        price_time = values[timestamp_idx] if timestamp_idx < len(values) else None
                    
                    logger.info(f"Latest price for {ticker}: {close_price} {currency} (as of {price_time})")
                    return {
                        "price": close_price,
                        "currency": currency,
                        "price_time": price_time
                    }
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing price data for {ticker}: {e}")
                    return None
            else:
                # No 15-min data, fall back to hourly
                logger.debug(f"No 15-min data for {ticker}, trying hourly...")
                return _get_hourly_price(entity_id, ticker, api_key)
        else:
            logger.error(f"Price API error for {ticker}: {response.status_code} - {response.text}")
            return None
            
    except requests.RequestException as e:
        logger.error(f"Request error fetching price for {ticker}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching price for {ticker}: {e}")
        return None


def _get_hourly_price(entity_id: str, ticker: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """
    Fallback to hourly price data if 15-min data not available.
    """
    try:
        key = _get_api_key(api_key)
        
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=2)
        
        response = requests.post(
            f"{BIGDATA_BASE_URL}/price/intraday/query",
            headers={
                "X-API-KEY": key,
                "Content-Type": "application/json"
            },
            json={
                "identifier": {
                    "type": "rp_entity_id",
                    "value": entity_id
                },
                "timestamp": {
                    "start": format_timestamp(start_time),
                    "end": format_timestamp(end_time)
                },
                "interval": "1hour"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", {})
            
            if results and "values" in results and results["values"]:
                values = results["values"]
                fields = results.get("fields", [])
                
                try:
                    close_idx = fields.index("CLOSE")
                    currency_idx = fields.index("CURRENCY")
                    timestamp_idx = fields.index("TIMESTAMP") if "TIMESTAMP" in fields else 0
                    
                    if isinstance(values[0], list):
                        latest_values = values[-1]
                        close_price = latest_values[close_idx]
                        currency = latest_values[currency_idx]
                        price_time = latest_values[timestamp_idx] if timestamp_idx < len(latest_values) else None
                    else:
                        close_price = values[close_idx]
                        currency = values[currency_idx]
                        price_time = values[timestamp_idx] if timestamp_idx < len(values) else None
                    
                    logger.info(f"Hourly price for {ticker}: {close_price} {currency} (as of {price_time})")
                    return {
                        "price": close_price,
                        "currency": currency,
                        "price_time": price_time
                    }
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing hourly price for {ticker}: {e}")
                    return None
        
        return None
    except Exception as e:
        logger.error(f"Error fetching hourly price for {ticker}: {e}")
        return None


def get_price_change(entity_id: str, ticker: str, api_key: Optional[str] = None) -> Optional[float]:
    """
    Fetch the 1D price change percentage for a ticker
    
    Args:
        entity_id: Bigdata entity ID
        ticker: Stock ticker symbol
        api_key: Optional API key (falls back to server default)
    
    Returns: float (percentage change) or None
    """
    try:
        key = _get_api_key(api_key)
        
        response = requests.post(
            f"{BIGDATA_BASE_URL}/price/changes/query",
            headers={
                "X-API-KEY": key,
                "Content-Type": "application/json"
            },
            json={
                "identifier": {
                    "type": "rp_entity_id",
                    "value": entity_id
                }
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            
            if results and len(results) > 0:
                change_1d = results[0].get("1D")
                logger.info(f"Price change for {ticker}: {change_1d}%")
                return change_1d
            else:
                logger.warning(f"No price change data for {ticker}")
                return None
        else:
            logger.error(f"Price change API error for {ticker}: {response.status_code}")
            return None
            
    except requests.RequestException as e:
        logger.error(f"Request error fetching price change for {ticker}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching price change for {ticker}: {e}")
        return None


def get_price_data(entity_id: str, ticker: str, api_key: Optional[str] = None) -> Dict:
    """
    Get complete price data (price + change) for a ticker with caching
    
    Args:
        entity_id: Bigdata entity ID
        ticker: Stock ticker symbol
        api_key: Optional API key (falls back to server default)
    
    Returns: {"price": float, "change": float, "currency": str}
    """
    # Check cache first
    if ticker in price_cache and is_cache_valid(price_cache[ticker]):
        logger.info(f"Price cache hit for {ticker}")
        return price_cache[ticker]
    
    logger.info(f"Fetching price data for {ticker}")
    
    # Fetch price and change
    price_data = get_latest_price(entity_id, ticker, api_key)
    change_data = get_price_change(entity_id, ticker, api_key)
    
    # Build result
    result = {
        "price": price_data.get("price") if price_data else None,
        "change": change_data,
        "currency": price_data.get("currency", "USD") if price_data else "USD",
        "timestamp": datetime.now(timezone.utc)
    }
    
    # Cache the result
    price_cache[ticker] = result
    
    return result


def get_prices_for_tickers(
    tickers_with_entities: List[Tuple[str, str]],
    api_key: Optional[str] = None
) -> Dict[str, Dict]:
    """
    Get price data for multiple tickers
    
    Args:
        tickers_with_entities: List of (ticker, entity_id) tuples
        api_key: Optional API key (falls back to server default)
    
    Returns:
        Dict mapping ticker to price data
    """
    results = {}
    
    for ticker, entity_id in tickers_with_entities:
        try:
            price_data = get_price_data(entity_id, ticker, api_key)
            results[ticker] = price_data
        except Exception as e:
            logger.error(f"Error fetching price for {ticker}: {e}")
            results[ticker] = {
                "price": None,
                "change": None,
                "currency": "USD",
                "timestamp": datetime.now(timezone.utc)
            }
    
    return results


def clear_cache():
    """Clear the entire price cache"""
    global price_cache
    price_cache = {}
    logger.info("Price cache cleared")


def clear_expired_cache():
    """Remove expired entries from cache"""
    global price_cache
    expired_keys = [
        ticker for ticker, data in price_cache.items()
        if not is_cache_valid(data)
    ]
    
    for key in expired_keys:
        del price_cache[key]
    
    if expired_keys:
        logger.info(f"Cleared {len(expired_keys)} expired price cache entries")


def get_price_for_date_range(
    entity_id: str,
    ticker: str,
    start_date: datetime,
    end_date: datetime,
    api_key: Optional[str] = None
) -> Optional[Dict]:
    """
    Fetch price data for a specific date range.
    
    Args:
        entity_id: Bigdata entity ID
        ticker: Stock ticker symbol
        start_date: Start datetime (UTC)
        end_date: End datetime (UTC)
        api_key: Optional API key (falls back to server default)
    
    Returns:
        Dict with "start_price", "end_price", "currency" or None
    """
    try:
        key = _get_api_key(api_key)
        
        # Ensure timezone-aware datetimes
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        response = requests.post(
            f"{BIGDATA_BASE_URL}/price/intraday/query",
            headers={
                "X-API-KEY": key,
                "Content-Type": "application/json"
            },
            json={
                "identifier": {
                    "type": "rp_entity_id",
                    "value": entity_id
                },
                "timestamp": {
                    "start": format_timestamp(start_date),
                    "end": format_timestamp(end_date)
                },
                "interval": "4hour"  # Use 4-hour intervals to get daily-level data (API doesn't support '1day')
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", {})
            
            if results and "values" in results and results["values"]:
                values = results["values"]
                fields = results.get("fields", [])
                
                try:
                    close_idx = fields.index("CLOSE")
                    currency_idx = fields.index("CURRENCY")
                    
                    # Get first and last prices from 4-hour interval data
                    if isinstance(values[0], list):
                        # Multiple data points - get first and last
                        first_values = values[0]
                        last_values = values[-1]
                        start_price = first_values[close_idx]
                        end_price = last_values[close_idx]
                        currency = first_values[currency_idx]
                    elif len(values) > 0:
                        # Single data point (same for start and end)
                        # Handle both list and non-list formats
                        if isinstance(values, list) and len(values) > close_idx:
                            start_price = values[close_idx]
                            end_price = values[close_idx]
                            currency = values[currency_idx] if currency_idx < len(values) else "USD"
                        else:
                            # Fallback: use first available price
                            start_price = values[0] if isinstance(values[0], (int, float)) else None
                            end_price = start_price
                            currency = "USD"
                    else:
                        logger.warning(f"No price values found for {ticker}")
                        return None
                    
                    logger.info(
                        f"Price range for {ticker}: "
                        f"{start_price} -> {end_price} {currency}"
                    )
                    
                    return {
                        "start_price": start_price,
                        "end_price": end_price,
                        "currency": currency
                    }
                except (ValueError, IndexError) as e:
                    logger.error(f"Error parsing price range data for {ticker}: {e}")
                    return None
            else:
                logger.warning(f"No price data available for {ticker} in date range")
                return None
        else:
            logger.error(
                f"Price API error for {ticker}: "
                f"{response.status_code} - {response.text}"
            )
            return None
            
    except requests.RequestException as e:
        logger.error(f"Request error fetching price range for {ticker}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching price range for {ticker}: {e}")
        return None


def get_prices_for_date_range_batch(
    tickers_with_entities: List[Tuple[str, str]],
    start_date: datetime,
    end_date: datetime,
    api_key: Optional[str] = None
) -> Dict[str, Dict]:
    """
    Get price data for multiple tickers over a date range.
    
    Args:
        tickers_with_entities: List of (ticker, entity_id) tuples
        start_date: Start datetime (UTC)
        end_date: End datetime (UTC)
        api_key: Optional API key (falls back to server default)
    
    Returns:
        Dict mapping ticker to price data with start_price and end_price
    """
    results = {}
    
    for ticker, entity_id in tickers_with_entities:
        try:
            price_data = get_price_for_date_range(
                entity_id, ticker, start_date, end_date, api_key
            )
            if price_data:
                results[ticker] = price_data
            else:
                results[ticker] = {
                    "start_price": None,
                    "end_price": None,
                    "currency": "USD"
                }
        except Exception as e:
            logger.error(f"Error fetching price range for {ticker}: {e}")
            results[ticker] = {
                "start_price": None,
                "end_price": None,
                "currency": "USD"
            }
    
    return results
