"""
Default multi-exchange watchlist for Top Movers analysis.

Mix of TSX, SGX, and Nasdaq symbols for daily gainers/decliners.
"""

from datetime import date
from typing import Dict, List


def default_report_title() -> str:
    """Default report title using today's date (e.g. Daily Movers - April 17, 2026)."""
    d = date.today()
    return f"Daily Movers - {d.strftime('%B')} {d.day}, {d.year}"

# Default watchlist — TSX, SGX, Nasdaq (30 symbols)
DEFAULT_WATCHLIST: List[str] = [
    "XTSE:RY",
    "XTSE:SHOP",
    "XTSE:TD",
    "XTSE:ENB",
    "XTSE:BN",
    "XTSE:CP",
    "XTSE:BMO",
    "XTSE:CNR",
    "XTSE:CNQ",
    "XTSE:BNS",
    "XSES:D05",
    "XSES:O39",
    "XSES:Z74",
    "XSES:U11",
    "XSES:S63",
    "XSES:J36",
    "XSES:F34",
    "XSES:S68",
    "XSES:H78",
    "XSES:BN4",
    "XNAS:NVDA",
    "XNAS:AAPL",
    "XNAS:MSFT",
    "XNAS:AMZN",
    "XNAS:GOOGL",
    "XNAS:AVGO",
    "XNAS:META",
    "XNAS:TSLA",
    "XNAS:ASML",
    "XNAS:MU",
]

# Ticker (normalized, no exchange) to display name
TICKER_COMPANY_MAP: Dict[str, str] = {
    "RY": "Royal Bank of Canada",
    "SHOP": "Shopify",
    "TD": "Toronto-Dominion Bank",
    "ENB": "Enbridge",
    "BN": "Brookfield Corporation",
    "CP": "Canadian Pacific Kansas City",
    "BMO": "Bank of Montreal",
    "CNR": "Canadian National Railway",
    "CNQ": "Canadian Natural Resources",
    "BNS": "Bank of Nova Scotia",
    "D05": "DBS Group Holdings",
    "O39": "OCBC Bank",
    "Z74": "Singtel",
    "U11": "UOB",
    "S63": "ST Engineering",
    "J36": "Jardine Matheson Holdings",
    "F34": "Wilmar International",
    "S68": "Singapore Exchange",
    "H78": "Hongkong Land Holdings",
    "BN4": "Keppel Corporation",
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "AVGO": "Broadcom",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "ASML": "ASML Holding",
    "MU": "Micron Technology",
}


def normalize_ticker(ticker: str) -> str:
    """
    Normalize ticker format.

    Handles both formats:
    - XSES:D05 -> D05
    - D05 -> D05

    Args:
        ticker: Ticker in any format

    Returns:
        Normalized ticker without exchange prefix
    """
    if ":" in ticker:
        return ticker.split(":")[-1].strip().upper()
    return ticker.strip().upper()


def get_exchange_ticker(ticker: str, exchange: str = "XSES") -> str:
    """
    Get ticker with exchange prefix.

    Args:
        ticker: Normalized ticker (e.g., D05)
        exchange: Exchange code (default: XSES)

    Returns:
        Exchange-prefixed ticker (e.g., XSES:D05)
    """
    normalized = normalize_ticker(ticker)
    return f"{exchange}:{normalized}"


def parse_tickers_input(tickers_input: str) -> List[str]:
    """
    Parse tickers from various input formats.

    Accepts:
    - Comma-separated: "D05, O39, U11"
    - Newline-separated
    - With or without exchange prefix

    Args:
        tickers_input: Raw ticker input string

    Returns:
        List of normalized tickers
    """
    if "," in tickers_input:
        raw_tickers = tickers_input.split(",")
    else:
        raw_tickers = tickers_input.strip().split()

    return [normalize_ticker(t) for t in raw_tickers if t.strip()]


def get_default_tickers_string() -> str:
    """
    Get default watchlist as comma-separated string.

    Returns:
        Comma-separated string of tickers
    """
    return ", ".join(DEFAULT_WATCHLIST)


def get_company_name(ticker: str) -> str:
    """
    Get company name for a ticker.

    Args:
        ticker: Ticker symbol (with or without exchange prefix)

    Returns:
        Company name or ticker if not found
    """
    normalized = normalize_ticker(ticker)
    return TICKER_COMPANY_MAP.get(normalized, normalized)
