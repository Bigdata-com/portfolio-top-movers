"""
SGX Top Movers Workflow

Main workflow for finding top movers and generating pre-sales reports.
"""

import asyncio
import csv
import json
import logging
import os
import sqlite3
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from config.watchlist import default_report_title

from .job_storage import JobStorage, JobStatus
from .topic_search_service import TopicSearchService
from .report_service import ReportService
from .price_service import get_price_data

logger = logging.getLogger(__name__)


@dataclass
class MoverData:
    """Data for a single mover (gainer or decliner)"""
    ticker: str
    company_name: str
    entity_id: Optional[str] = None
    current_price: Optional[float] = None
    price_change: Optional[float] = None
    price_change_pct: Optional[float] = None
    currency: str = "SGD"
    news_data: Optional[Dict] = None
    briefs: Optional[List] = None
    summary: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "entity_id": self.entity_id,
            "current_price": self.current_price,
            "price_change": self.price_change,
            "price_change_pct": self.price_change_pct,
            "currency": self.currency,
        }


@dataclass
class MoversReportRequest:
    """Request for movers report generation"""
    tickers: List[str]
    report_name: str = field(default_factory=default_report_title)
    top_n: int = 5
    days_lookback: int = 1  # Days to look back for news
    use_mini_topics: bool = True  # Use reduced topic set for faster processing
    custom_topics: Optional[List[Dict[str, str]]] = None  # Custom topics override defaults
    api_key: Optional[str] = None  # Bigdata API key (uses server default if not provided)


class JobLogHandler(logging.Handler):
    """Custom logging handler that sends logs to job storage"""
    
    def __init__(self, job_storage: JobStorage, job_id: str):
        super().__init__()
        self.job_storage = job_storage
        self.job_id = job_id
    
    def emit(self, record):
        """Emit a log record to job storage"""
        try:
            log_message = self.format(record)
            message = log_message
            if ' - ' in log_message:
                parts = log_message.split(' - ', 3)
                if len(parts) >= 4:
                    message = parts[-1]
                elif len(parts) >= 2:
                    message = parts[-1]
            
            self.job_storage.add_log(
                self.job_id,
                record.levelname,
                message
            )
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            logger.warning(
                "Failed to persist job log for %s: %s",
                self.job_id,
                exc,
                exc_info=True,
            )


def normalize_ticker(ticker: str) -> str:
    """Normalize ticker to plain format (without exchange prefix)"""
    if ":" in ticker:
        return ticker.split(":")[-1].strip().upper()
    return ticker.strip().upper()


async def fetch_entity_ids_batch(
    tickers: List[str],
    topic_search_service: TopicSearchService
) -> Dict[str, Dict[str, str]]:
    """
    Fetch entity IDs for multiple tickers in batch.
    
    Args:
        tickers: List of normalized ticker symbols
        topic_search_service: TopicSearchService instance
        
    Returns:
        Dict mapping ticker to {"entity_id": "...", "company_name": "..."}
    """
    results = {}
    
    # Fetch company data for all tickers in parallel
    tasks = [
        topic_search_service.get_company_data(ticker)
        for ticker in tickers
    ]
    
    company_data_list = await asyncio.gather(*tasks, return_exceptions=True)
    
    for ticker, company_data in zip(tickers, company_data_list):
        if isinstance(company_data, Exception):
            logger.error(f"Error fetching entity ID for {ticker}: {company_data}")
            results[ticker] = {
                "entity_id": None,
                "company_name": ticker
            }
        elif company_data:
            results[ticker] = {
                "entity_id": company_data.entity_id,
                "company_name": company_data.company_name
            }
        else:
            logger.warning(f"No entity ID found for {ticker}")
            results[ticker] = {
                "entity_id": None,
                "company_name": ticker
            }
    
    return results


def _fetch_single_price(ticker: str, entity_id: str, api_key: Optional[str] = None) -> tuple:
    """
    Fetch price data for a single ticker.
    
    Args:
        ticker: Stock ticker symbol
        entity_id: Entity ID for the ticker
        api_key: Optional Bigdata API key
        
    Returns:
        Tuple of (ticker, price_data_dict)
    """
    try:
        if not entity_id:
            logger.warning(f"No entity_id for {ticker}, skipping price fetch")
            return ticker, {
                "price": None,
                "change_pct": None,
                "change_abs": None,
                "currency": "SGD"
            }
        
        # Fetch both price and change percentage
        price_data = get_price_data(entity_id, ticker, api_key)
        
        price = price_data.get("price")
        change_pct = price_data.get("change")
        currency = price_data.get("currency", "SGD")
        
        # Calculate absolute change if we have both price and percentage
        change_abs = None
        if price is not None and change_pct is not None:
            original_price = price / (1 + change_pct / 100)
            change_abs = price - original_price
        
        return ticker, {
            "price": price,
            "change_pct": change_pct,
            "change_abs": change_abs,
            "currency": currency
        }
        
    except Exception as e:
        logger.error(f"Error fetching price for {ticker}: {e}")
        return ticker, {
            "price": None,
            "change_pct": None,
            "change_abs": None,
            "currency": "SGD"
        }


def fetch_price_changes_batch(
    tickers_with_entities: List[tuple],
    max_workers: int = 5,
    api_key: Optional[str] = None
) -> Dict[str, Dict]:
    """
    Fetch price data (price + 1-day change) for multiple tickers in parallel.
    
    Args:
        tickers_with_entities: List of (ticker, entity_id) tuples
        max_workers: Number of parallel threads (default: 5)
        api_key: Optional Bigdata API key (uses server default if not provided)
        
    Returns:
        Dict mapping ticker to price data with price, change_pct, change_abs, currency
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results = {}
    
    logger.info(f"Fetching prices for {len(tickers_with_entities)} tickers with {max_workers} parallel threads")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_ticker = {
            executor.submit(_fetch_single_price, ticker, entity_id, api_key): ticker
            for ticker, entity_id in tickers_with_entities
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                result_ticker, price_data = future.result()
                results[result_ticker] = price_data
            except Exception as e:
                logger.error(f"Error in thread for {ticker}: {e}")
                results[ticker] = {
                    "price": None,
                    "change_pct": None,
                    "change_abs": None,
                    "currency": "SGD"
                }
    
    logger.info(f"Completed fetching prices for {len(results)} tickers")
    return results


def find_top_movers(
    movers: List[MoverData],
    top_n: int = 5
) -> Dict[str, List[MoverData]]:
    """
    Find top N gainers and top N decliners.
    
    Args:
        movers: List of MoverData with price changes
        top_n: Number of top movers to return
        
    Returns:
        Dict with 'gainers' and 'decliners' lists
    """
    # Filter out movers without price change data
    valid_movers = [m for m in movers if m.price_change_pct is not None]
    
    # Sort by price change percentage
    sorted_movers = sorted(valid_movers, key=lambda m: m.price_change_pct or 0, reverse=True)
    
    # Get top gainers (positive changes) and top decliners (negative changes)
    gainers = [m for m in sorted_movers if (m.price_change_pct or 0) > 0][:top_n]
    decliners = [m for m in sorted_movers if (m.price_change_pct or 0) < 0][-top_n:][::-1]  # Reverse to get most negative first
    
    # If not enough decliners, take from bottom of sorted list
    if len(decliners) < top_n:
        decliners = sorted_movers[-top_n:][::-1]
    
    return {
        "gainers": gainers,
        "decliners": decliners
    }


async def fetch_news_for_mover(
    mover: MoverData,
    topic_search_service: TopicSearchService,
    days: int = 1,
    use_mini_topics: bool = True,
    custom_topics: Optional[List[Dict[str, str]]] = None
) -> MoverData:
    """
    Fetch news for a single mover.
    
    Args:
        mover: MoverData object
        topic_search_service: TopicSearchService instance
        days: Days to look back for news
        use_mini_topics: Use reduced topic set
        custom_topics: Custom topics to use (overrides default topics)
        
    Returns:
        Updated MoverData with news_data
    """
    try:
        # Import topics
        from config.topics import get_topics_for_company, format_topic_for_company
        
        # Use custom topics if provided, otherwise get default topics
        if custom_topics:
            # Format custom topics with company name
            topics_for_search = [
                format_topic_for_company(t, mover.company_name) 
                for t in custom_topics
            ]
        else:
            topics_for_search = get_topics_for_company(mover.company_name, mini=use_mini_topics)
        
        logger.info(f"Fetching news for {mover.ticker} ({mover.company_name})")
        
        search_results = await topic_search_service.search_ticker(
            ticker=mover.ticker,
            days=days,
            custom_topics=topics_for_search,
            min_relevance=0.0,
            query_reformulation=False
        )
        
        if "error" not in search_results:
            mover.news_data = {
                "ticker": search_results.get("ticker"),
                "company_name": search_results.get("company_name"),
                "entity_id": search_results.get("entity_id"),
                "topic_results": search_results.get("topic_results", []),
                "total_results": search_results.get("total_results", 0)
            }
            logger.info(f"Found {search_results.get('total_results', 0)} news articles for {mover.ticker}")
        else:
            logger.warning(f"Failed to fetch news for {mover.ticker}: {search_results.get('error')}")
            mover.news_data = None
            
    except Exception as e:
        logger.error(f"Error fetching news for {mover.ticker}: {e}")
        mover.news_data = None
    
    return mover


async def generate_mover_summary(
    mover: MoverData,
    report_service: ReportService,
    movement_type: str,
    job_folder: Optional[Path] = None
) -> MoverData:
    """
    Generate summary commentary for a mover.
    
    Args:
        mover: MoverData with news_data
        report_service: ReportService instance
        movement_type: "gainer" or "decliner"
        job_folder: Optional folder for saving prompts
        
    Returns:
        Updated MoverData with summary
    """
    if not mover.news_data or not mover.news_data.get("topic_results"):
        logger.warning(f"No news data for {mover.ticker}, skipping summary generation")
        mover.summary = f"No significant news found for {mover.company_name} in the past 24 hours."
        return mover
    
    try:
        # Generate briefs first
        news_response = {
            "ticker": mover.ticker,
            "company_name": mover.company_name,
            "topic_results": mover.news_data.get("topic_results", [])
        }
        
        briefing_prompt_path = None
        if job_folder:
            briefing_prompt_path = str(job_folder / f"briefing_prompt_{mover.ticker}.md")
        
        briefs = await report_service.generate_topic_briefs(news_response, save_prompt_path=briefing_prompt_path)
        mover.briefs = briefs
        logger.info(f"Generated {len(briefs)} briefs for {mover.ticker}")
        
        # Generate desk note from briefs
        if briefs:
            desk_prompt_path = None
            if job_folder:
                desk_prompt_path = str(job_folder / f"desk_note_prompt_{mover.ticker}.md")
            
            desk_note = await report_service.generate_desk_note(briefs, save_prompt_path=desk_prompt_path)
            mover.summary = desk_note
            logger.info(f"Generated summary for {mover.ticker}")
        else:
            mover.summary = f"No significant developments found for {mover.company_name}."
        
    except Exception as e:
        logger.error(f"Error generating summary for {mover.ticker}: {e}", exc_info=True)
        mover.summary = f"Unable to generate summary for {mover.company_name}."
    
    return mover


def format_movers_table(movers: List[MoverData], title: str) -> str:
    """
    Format movers as markdown table.
    
    Args:
        movers: List of MoverData
        title: Table title
        
    Returns:
        Markdown table string
    """
    lines = [f"## {title}\n"]
    lines.append("| # | Ticker | Company | Price | Change | % Change |")
    lines.append("|---|--------|---------|-------|--------|----------|")
    
    for i, mover in enumerate(movers, 1):
        price_str = f"{mover.current_price:.2f}" if mover.current_price else "N/A"
        change_str = f"{mover.price_change:+.2f}" if mover.price_change else "N/A"
        pct_str = f"{mover.price_change_pct:+.2f}%" if mover.price_change_pct else "N/A"
        
        lines.append(f"| {i} | {mover.ticker} | {mover.company_name} | {price_str} | {change_str} | {pct_str} |")
    
    return "\n".join(lines)


def format_movers_commentary(movers: List[MoverData], title: str) -> str:
    """
    Format movers commentary section.
    
    Args:
        movers: List of MoverData with summaries
        title: Section title
        
    Returns:
        Markdown commentary string
    """
    lines = [f"### {title}\n"]
    
    for i, mover in enumerate(movers, 1):
        pct_str = f"{mover.price_change_pct:+.2f}%" if mover.price_change_pct else "N/A"
        lines.append(f"#### {i}. {mover.company_name} ({mover.ticker}) - {pct_str}\n")
        lines.append(mover.summary or "No commentary available.")
        lines.append("")
    
    return "\n".join(lines)


def generate_final_report(
    gainers: List[MoverData],
    decliners: List[MoverData],
    report_name: str,
    watchlist_size: int,
    top_n: int = 5
) -> str:
    """
    Generate the final markdown report.
    
    Args:
        gainers: List of top gainers with summaries
        decliners: List of top decliners with summaries
        report_name: Report title
        watchlist_size: Number of stocks in watchlist
        top_n: Number of top movers to display
        
    Returns:
        Complete markdown report
    """
    now = datetime.now()
    
    lines = [
        f"# {report_name}",
        "",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Watchlist:** {watchlist_size} SGX Stocks",
        "",
        "---",
        "",
    ]
    
    # Top Gainers
    lines.append(format_movers_table(gainers, f"Top {top_n} Gainers"))
    lines.append("")
    lines.append(format_movers_commentary(gainers, f"Commentary: Top {top_n} Gainers"))
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Top Decliners
    lines.append(format_movers_table(decliners, f"Top {top_n} Decliners"))
    lines.append("")
    lines.append(format_movers_commentary(decliners, f"Commentary: Top {top_n} Decliners"))
    
    return "\n".join(lines)


def save_search_results_csv(
    movers: List[MoverData],
    job_folder: Path
) -> None:
    """Save search results to CSV."""
    csv_path = job_folder / "search_results.csv"
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'ticker', 'company_name', 'topic_name', 'entity_id',
            'doc_id', 'headline', 'timestamp', 'source_name',
            'url', 'chunk_text', 'relevance'
        ])
        
        for mover in movers:
            if not mover.news_data or not mover.news_data.get("topic_results"):
                continue
            
            for article in mover.news_data.get("topic_results", []):
                source = article.get("source", {})
                source_name = source.get("name", "") if isinstance(source, dict) else str(source)
                
                writer.writerow([
                    mover.ticker,
                    mover.company_name,
                    article.get("topic_name", ""),
                    mover.entity_id or "",
                    article.get("id", ""),
                    article.get("headline", ""),
                    article.get("timestamp", ""),
                    source_name,
                    article.get("document_url", ""),
                    article.get("full_text", ""),
                    article.get("relevance", "")
                ])
    
    logger.info(f"Saved search results to {csv_path}")


async def run_movers_workflow(
    job_id: str,
    request: MoversReportRequest,
    job_storage: JobStorage,
    topic_search_service: TopicSearchService,
    report_service: ReportService
) -> None:
    """
    Main workflow for generating movers report.
    
    Args:
        job_id: Unique job identifier
        request: MoversReportRequest
        job_storage: JobStorage instance
        topic_search_service: TopicSearchService instance
        report_service: ReportService instance
    """
    # Set up logging handler
    job_log_handler = JobLogHandler(job_storage, job_id)
    job_log_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    job_log_handler.setFormatter(formatter)
    
    workflow_logger = logging.getLogger('services.movers_workflow')
    workflow_logger.addHandler(job_log_handler)
    
    try:
        job_storage.update_job_status(job_id, JobStatus.PROCESSING)
        logger.info(f"Starting movers workflow for job {job_id}")
        
        # Create job folder
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        job_folder = output_dir / job_id
        job_folder.mkdir(exist_ok=True)
        
        # Step 1: Parse and normalize tickers
        logger.info(f"Processing {len(request.tickers)} tickers")
        tickers = [normalize_ticker(t) for t in request.tickers]
        
        # Step 2: Fetch entity IDs
        logger.info("Fetching entity IDs...")
        entity_data = await fetch_entity_ids_batch(tickers, topic_search_service)
        
        # Step 3: Fetch price changes
        logger.info("Fetching price changes...")
        tickers_with_entities = [
            (ticker, entity_data.get(ticker, {}).get("entity_id"))
            for ticker in tickers
        ]
        price_data = fetch_price_changes_batch(tickers_with_entities, api_key=request.api_key)
        
        # Step 4: Create MoverData objects
        movers = []
        for ticker in tickers:
            entity_info = entity_data.get(ticker, {})
            price_info = price_data.get(ticker, {})
            
            movers.append(MoverData(
                ticker=ticker,
                company_name=entity_info.get("company_name", ticker),
                entity_id=entity_info.get("entity_id"),
                current_price=price_info.get("price"),
                price_change=price_info.get("change_abs"),
                price_change_pct=price_info.get("change_pct"),
                currency=price_info.get("currency", "SGD")
            ))
        
        # Step 5: Find top movers
        logger.info(f"Finding top {request.top_n} movers...")
        top_movers = find_top_movers(movers, request.top_n)
        gainers = top_movers["gainers"]
        decliners = top_movers["decliners"]
        
        logger.info(f"Found {len(gainers)} gainers and {len(decliners)} decliners")
        
        # Step 6: Fetch news for all movers
        all_movers = gainers + decliners
        logger.info(f"Fetching news for {len(all_movers)} movers...")
        
        news_tasks = [
            fetch_news_for_mover(
                mover, 
                topic_search_service, 
                days=request.days_lookback, 
                use_mini_topics=request.use_mini_topics,
                custom_topics=request.custom_topics
            )
            for mover in all_movers
        ]
        all_movers = await asyncio.gather(*news_tasks)
        
        # Split back into gainers and decliners
        gainers = all_movers[:len(gainers)]
        decliners = all_movers[len(gainers):]
        
        # Save search results CSV
        save_search_results_csv(list(gainers) + list(decliners), job_folder)
        
        # Step 7: Generate summaries for all movers
        logger.info("Generating summaries...")
        
        summary_tasks = []
        for mover in gainers:
            summary_tasks.append(generate_mover_summary(mover, report_service, "gainer", job_folder))
        for mover in decliners:
            summary_tasks.append(generate_mover_summary(mover, report_service, "decliner", job_folder))
        
        all_movers_with_summaries = await asyncio.gather(*summary_tasks)
        
        gainers = list(all_movers_with_summaries[:len(gainers)])
        decliners = list(all_movers_with_summaries[len(gainers):])
        
        # Step 8: Generate final report
        logger.info("Generating final report...")
        report_content = generate_final_report(
            gainers=gainers,
            decliners=decliners,
            report_name=request.report_name,
            watchlist_size=len(request.tickers),
            top_n=request.top_n
        )
        
        # Save report
        report_path = job_folder / "report.md"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        logger.info(f"Report saved to {report_path}")
        
        # Save movers data as JSON
        movers_json_path = job_folder / "movers_data.json"
        movers_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_name": request.report_name,
            "watchlist_size": len(request.tickers),
            "gainers": [m.to_dict() for m in gainers],
            "decliners": [m.to_dict() for m in decliners]
        }
        with open(movers_json_path, 'w', encoding='utf-8') as f:
            json.dump(movers_data, f, indent=2)
        
        # Update job status
        job_storage.update_job_status(
            job_id,
            JobStatus.COMPLETE,
            result={
                "report_name": request.report_name,
                "gainers_count": len(gainers),
                "decliners_count": len(decliners),
                "watchlist_size": len(request.tickers)
            },
            report_path=str(report_path)
        )
        
        logger.info(f"Movers workflow completed for job {job_id}")
        
    except Exception as e:
        logger.error(f"Error in movers workflow for job {job_id}: {e}", exc_info=True)
        job_storage.update_job_status(
            job_id,
            JobStatus.FAILED,
            error=str(e)
        )
    finally:
        workflow_logger.removeHandler(job_log_handler)
        # Close the topic search service to prevent connection leaks
        if topic_search_service:
            try:
                await topic_search_service.close()
                logger.info(f"TopicSearchService closed for job {job_id}")
            except Exception as e:
                logger.warning(f"Error closing TopicSearchService for job {job_id}: {e}")