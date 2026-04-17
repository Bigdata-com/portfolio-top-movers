#!/usr/bin/env python3
"""
SGX Top Movers Report Server

FastAPI server for generating pre-sales reports showing top gainers and decliners
from an SGX watchlist with AI-powered news analysis.
"""

import os
import sys
import shutil
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

output_dir = Path("output")
output_dir.mkdir(exist_ok=True)

logger = logging.getLogger()
logger.setLevel(getattr(logging, log_level, logging.INFO))
logger.handlers.clear()

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(getattr(logging, log_level, logging.INFO))
console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# File handler
log_file = output_dir / "app.log"
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(getattr(logging, log_level, logging.INFO))
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# Configuration
# Server-side default API key (optional - users can provide their own via header)
DEFAULT_BIGDATA_API_KEY = os.getenv("BIGDATA_API_KEY")
BIGDATA_BASE_URL = "https://api.bigdata.com/v1"

if not DEFAULT_BIGDATA_API_KEY:
    logger.warning("BIGDATA_API_KEY not found in environment - users must provide their own API key")


def get_bigdata_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-KEY")) -> str:
    """
    Resolve Bigdata API key from request header or server default.
    
    Priority:
    1. X-API-KEY header from client
    2. Server-side BIGDATA_API_KEY environment variable
    
    Raises HTTPException if no key is available.
    """
    api_key = x_api_key or os.getenv("BIGDATA_API_KEY")
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "API key required",
                "message": "Please configure your Bigdata API key in Settings"
            }
        )
    
    return api_key

# Import services
sys.path.insert(0, str(Path(__file__).parent))

from services.topic_search_service import TopicSearchService
from services.report_service import ReportService
from services.job_storage import job_storage, JobStatus
from services.movers_workflow import run_movers_workflow, MoversReportRequest
from config.watchlist import (
    DEFAULT_WATCHLIST,
    default_report_title,
    get_default_tickers_string,
    normalize_ticker,
)
from config.topics import MOVERS_TOPICS, MOVERS_TOPICS_MINI, STANDARD_TOPICS

# Global service instances
topic_search_service: Optional[TopicSearchService] = None
report_service: Optional[ReportService] = None


# Topic model for custom topics
class TopicItem(BaseModel):
    """Single topic item"""
    topic_name: str
    topic_text: str


# Request/Response Models
class CreateReportRequest(BaseModel):
    """Request model for creating a movers report"""
    tickers: Optional[List[str]] = None  # If None, use default watchlist
    report_name: str = Field(default_factory=default_report_title)
    top_n: int = 5
    days_lookback: int = 1  # Days to look back for news
    use_mini_topics: bool = True
    custom_topics: Optional[List[TopicItem]] = None  # Custom topics override defaults


class CreateReportResponse(BaseModel):
    """Response model for report creation"""
    request_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Response model for job status"""
    job_id: str
    status: str
    created_at: str
    updated_at: str
    report_path: Optional[str] = None
    error: Optional[str] = None
    result: Optional[dict] = None


# Cleanup configuration
CLEANUP_INTERVAL_MINUTES = 30  # Run cleanup every 30 minutes
LOG_MAX_AGE_HOURS = 3  # Delete logs older than 3 hours
REPORT_MAX_AGE_DAYS = 5  # Delete reports older than 5 days

cleanup_task: Optional[asyncio.Task] = None


async def cleanup_old_data():
    """
    Background task to clean up old logs and reports.
    - Deletes log file entries older than LOG_MAX_AGE_HOURS
    - Deletes job folders and DB entries older than REPORT_MAX_AGE_DAYS
    """
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)
            
            now = datetime.now(timezone.utc)
            logger.info("Running scheduled cleanup...")
            
            # 1. Truncate log file (keep only recent entries)
            log_file = Path("output") / "app.log"
            if log_file.exists():
                try:
                    cutoff_time = now - timedelta(hours=LOG_MAX_AGE_HOURS)
                    lines_to_keep = []
                    
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            try:
                                # Parse timestamp from log line (format: 2026-01-22 11:03:07,789)
                                if ' - ' in line:
                                    timestamp_str = line.split(' - ')[0].strip()
                                    log_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                                    log_time = log_time.replace(tzinfo=timezone.utc)
                                    if log_time >= cutoff_time:
                                        lines_to_keep.append(line)
                                else:
                                    lines_to_keep.append(line)
                            except (ValueError, IndexError):
                                lines_to_keep.append(line)
                    
                    with open(log_file, 'w', encoding='utf-8') as f:
                        f.writelines(lines_to_keep)
                    
                    logger.info(f"Log cleanup: kept {len(lines_to_keep)} recent log entries")
                except Exception as e:
                    logger.warning(f"Error cleaning up log file: {e}")
            
            # 2. Delete old job folders and DB entries
            cutoff_date = now - timedelta(days=REPORT_MAX_AGE_DAYS)
            deleted_jobs = 0
            
            # Get old jobs from storage
            old_jobs = job_storage.list_jobs(limit=1000)
            for job in old_jobs:
                try:
                    job_created = job.get("created_at")
                    if job_created and job_created < cutoff_date:
                        job_id = job["job_id"]
                        
                        # Delete job folder
                        job_folder = Path("output") / job_id
                        if job_folder.exists():
                            shutil.rmtree(job_folder)
                        
                        # Delete from database
                        job_storage.delete_job(job_id)
                        deleted_jobs += 1
                except Exception as e:
                    logger.warning(f"Error deleting old job {job.get('job_id')}: {e}")
            
            if deleted_jobs > 0:
                logger.info(f"Cleanup: deleted {deleted_jobs} jobs older than {REPORT_MAX_AGE_DAYS} days")
            
            logger.info("Scheduled cleanup completed")
            
        except asyncio.CancelledError:
            logger.info("Cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")
            await asyncio.sleep(60)  # Wait a minute before retrying


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage service lifecycle"""
    global topic_search_service, report_service, cleanup_task
    
    logger.info("Starting up: Initializing services...")
    if os.getenv("BIGDATA_API_KEY", "").strip():
        logger.info("BIGDATA_API_KEY is set; clients may omit X-API-KEY for job/report routes")
    else:
        logger.warning(
            "BIGDATA_API_KEY is not set; clients must send X-API-KEY on job/report and report-creation routes"
        )

    # TopicSearchService will be created per-request with the appropriate API key
    # We only create a default one if we have a server-side key
    server_bigdata = os.getenv("BIGDATA_API_KEY")
    if server_bigdata:
        topic_search_service = TopicSearchService(
            api_key=server_bigdata,
            base_url=BIGDATA_BASE_URL
        )
        logger.info("TopicSearchService initialized with server default key")
    else:
        topic_search_service = None
        logger.info("TopicSearchService will be created per-request (no server default key)")
    
    try:
        report_service = ReportService()
        logger.info(
            f"ReportService initialized "
            f"(provider: {report_service.llm_service.provider_name}, "
            f"model: {report_service.llm_service.model})"
        )
    except Exception as e:
        logger.error(f"ReportService initialization failed: {e}", exc_info=True)
        report_service = None
    
    # Start background cleanup task
    cleanup_task = asyncio.create_task(cleanup_old_data())
    logger.info(f"Cleanup task started (logs: {LOG_MAX_AGE_HOURS}h, reports: {REPORT_MAX_AGE_DAYS}d)")
    
    yield
    
    logger.info("Shutting down: Closing services...")
    
    # Cancel cleanup task
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
    
    if topic_search_service:
        await topic_search_service.close()
    logger.info("Services closed")


# FastAPI app
app = FastAPI(
    title="Top Movers Commentary",
    description="Generate AI-powered pre-sales reports for SGX top gainers and decliners",
    version="1.0.0",
    lifespan=lifespan
)

# Serve static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/favicon.ico")
async def favicon():
    """Serve favicon (prefer .ico at app root or under static/, then .png)."""
    from fastapi.responses import Response

    base = Path(__file__).parent
    for path, media_type in (
        (base / "favicon.ico", "image/x-icon"),
        (base / "static" / "favicon.ico", "image/x-icon"),
        (base / "favicon.png", "image/png"),
    ):
        if path.exists():
            return FileResponse(path, media_type=media_type)
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the web interface"""
    html_file = Path(__file__).parent / "static" / "index.html"
    if html_file.exists():
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    return """
    <html>
        <head><title>SGX Top Movers</title></head>
        <body>
            <h1>Top Movers Commentary</h1>
            <p>API is running. See <a href="/docs">/docs</a> for API documentation.</p>
        </body>
    </html>
    """


@app.post("/api/report", response_model=CreateReportResponse)
async def create_report(
    request: CreateReportRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    api_key: str = Depends(get_bigdata_api_key),
):
    """
    Create a new movers report job.
    
    Returns HTTP 202 Accepted with job_id for status tracking.
    
    Requires a Bigdata key via **X-API-KEY** and/or server **BIGDATA_API_KEY**
    (same rule as other job/report routes).
    """
    # Use default watchlist if no tickers provided
    tickers = request.tickers or DEFAULT_WATCHLIST
    
    # Normalize tickers
    tickers = [normalize_ticker(t) for t in tickers]
    
    if len(tickers) < request.top_n * 2:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {request.top_n * 2} tickers to find top {request.top_n} movers"
        )
    
    if not report_service:
        raise HTTPException(
            status_code=503,
            detail="Report service not available. Check LLM provider configuration."
        )
    
    # Convert custom topics if provided
    custom_topics_list = None
    if request.custom_topics:
        custom_topics_list = [
            {"topic_name": t.topic_name, "topic_text": t.topic_text}
            for t in request.custom_topics
        ]
    
    # Create job
    request_data = {
        "tickers": tickers,
        "report_name": request.report_name,
        "top_n": request.top_n,
        "days_lookback": request.days_lookback,
        "use_mini_topics": request.use_mini_topics,
        "custom_topics": custom_topics_list
    }
    job_id = job_storage.create_job(request_data)
    
    # Create workflow request
    workflow_request = MoversReportRequest(
        tickers=tickers,
        report_name=request.report_name,
        top_n=request.top_n,
        days_lookback=request.days_lookback,
        use_mini_topics=request.use_mini_topics,
        custom_topics=custom_topics_list,
        api_key=api_key  # Pass the resolved API key for price fetching
    )
    
    # Create TopicSearchService with the resolved API key
    # This ensures each job uses the correct key (client or default)
    request_topic_search_service = TopicSearchService(
        api_key=api_key,
        base_url=BIGDATA_BASE_URL
    )
    
    # Spawn background task
    background_tasks.add_task(
        run_movers_workflow,
        job_id=job_id,
        request=workflow_request,
        job_storage=job_storage,
        topic_search_service=request_topic_search_service,
        report_service=report_service
    )
    
    client_bigdata = bool(http_request.headers.get("X-API-KEY"))
    logger.info(
        f"Created movers report job: {job_id} (using {'client' if client_bigdata else 'server'} Bigdata API key)"
    )
    
    return CreateReportResponse(
        request_id=job_id,
        status="pending",
        message="Movers report generation started"
    )


@app.get("/api/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, _key: str = Depends(get_bigdata_api_key)):
    """Get the status of a report job."""
    job = job_storage.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job["created_at"].isoformat(),
        updated_at=job["updated_at"].isoformat(),
        report_path=job.get("report_path"),
        error=job.get("error"),
        result=job.get("result")
    )


@app.get("/api/reports")
async def list_reports(limit: int = 50, _key: str = Depends(get_bigdata_api_key)):
    """List all report jobs."""
    jobs = job_storage.list_jobs(limit=limit)
    
    result_jobs = []
    for job in jobs:
        request_data = job.get("request_data", {})
        job_dict = {
            "job_id": job["job_id"],
            "status": job["status"],
            "report_name": request_data.get("report_name", "Unknown"),
            "top_n": request_data.get("top_n", 5),
            "watchlist_size": len(request_data.get("tickers", [])),
            "created_at": job["created_at"].isoformat(),
            "updated_at": job["updated_at"].isoformat(),
            "report_path": job.get("report_path"),
            "error": job.get("error"),
            "result": job.get("result")
        }
        result_jobs.append(job_dict)
    
    return {
        "jobs": result_jobs,
        "total": len(jobs)
    }


@app.get("/api/report/{job_id}/download")
async def download_report(job_id: str, _key: str = Depends(get_bigdata_api_key)):
    """Download the generated report."""
    job = job_storage.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    if job["status"] != JobStatus.COMPLETE.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not complete (status: {job['status']})"
        )
    
    report_path = job.get("report_path")
    if not report_path or not Path(report_path).exists():
        raise HTTPException(
            status_code=404,
            detail=f"Report file not found for job {job_id}"
        )
    
    return FileResponse(
        report_path,
        media_type="text/markdown",
        filename=f"movers_report_{job_id}.md"
    )


@app.get("/api/report/{job_id}/view")
async def view_report(job_id: str, _key: str = Depends(get_bigdata_api_key)):
    """Get report content for viewing in UI."""
    job = job_storage.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    if job["status"] != JobStatus.COMPLETE.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not complete (status: {job['status']})"
        )
    
    report_path = job.get("report_path")
    if not report_path or not Path(report_path).exists():
        raise HTTPException(
            status_code=404,
            detail=f"Report file not found for job {job_id}"
        )
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return PlainTextResponse(content=content, media_type="text/plain")


@app.get("/api/report/{job_id}/search-results")
async def download_search_results(job_id: str, _key: str = Depends(get_bigdata_api_key)):
    """Download search results CSV."""
    job = job_storage.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    if job["status"] != JobStatus.COMPLETE.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not complete"
        )
    
    job_folder = Path("output") / job_id
    csv_path = job_folder / "search_results.csv"
    
    if not csv_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Search results not found for job {job_id}"
        )
    
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename=f"search_results_{job_id}.csv"
    )


@app.get("/api/report/{job_id}/movers-data")
async def get_movers_data(job_id: str, _key: str = Depends(get_bigdata_api_key)):
    """Get movers data JSON."""
    job = job_storage.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    if job["status"] != JobStatus.COMPLETE.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not complete"
        )
    
    job_folder = Path("output") / job_id
    json_path = job_folder / "movers_data.json"
    
    if not json_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Movers data not found for job {job_id}"
        )
    
    import json
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return JSONResponse(content=data)


@app.delete("/api/report/{job_id}")
async def delete_job(job_id: str, _key: str = Depends(get_bigdata_api_key)):
    """Delete a job and its files."""
    job = job_storage.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    deleted = job_storage.delete_job(job_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    # Delete job folder
    job_folder = Path("output") / job_id
    if job_folder.exists():
        try:
            shutil.rmtree(job_folder)
            logger.info(f"Deleted job folder: {job_folder}")
        except Exception as e:
            logger.warning(f"Failed to delete job folder: {e}")
    
    return {"message": f"Job {job_id} deleted", "job_id": job_id}


@app.get("/api/config")
async def get_public_config():
    """Non-secret flags for the UI (e.g. whether server provides a Bigdata default key)."""
    return {"server_has_bigdata_key": bool(os.getenv("BIGDATA_API_KEY", "").strip())}


@app.get("/api/watchlist")
async def get_default_watchlist():
    """Get the default SGX watchlist."""
    return {
        "watchlist": DEFAULT_WATCHLIST,
        "count": len(DEFAULT_WATCHLIST),
        "tickers_string": get_default_tickers_string()
    }


@app.get("/api/topics")
async def get_available_topics():
    """Get available topic templates."""
    topic_names = sorted(
        {
            t["topic_name"]
            for t in (MOVERS_TOPICS + MOVERS_TOPICS_MINI + STANDARD_TOPICS)
        }
    )

    return {
        "topics_full": MOVERS_TOPICS,
        "topics_standard": STANDARD_TOPICS,
        "topics_mini": MOVERS_TOPICS_MINI,
        "topic_names": topic_names,
        "default_selection": [t["topic_name"] for t in MOVERS_TOPICS_MINI],
    }


@app.get("/api/logs/{job_id}")
async def get_job_logs(
    job_id: str,
    since: Optional[str] = None,
    _key: str = Depends(get_bigdata_api_key),
):
    """Get logs for a job."""
    job = job_storage.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    logs = job_storage.get_logs(job_id, since=since_dt)
    
    return {
        "job_id": job_id,
        "logs": logs,
        "count": len(logs)
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
