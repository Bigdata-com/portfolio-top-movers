"""
Job Status Storage Service

Provides SQLite-based persistent storage for jobs and logs.
"""

import os
import uuid
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Optional, List
from enum import Enum
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class JobStorage:
    """
    Job status storage service using SQLite database.
    
    Provides persistent storage for jobs and logs across application restarts.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize job storage with SQLite database.
        
        Args:
            db_path: Path to SQLite database file. If None, uses DB_STRING from env or defaults to jobs.db
        """
        if db_path is None:
            db_string = os.getenv("DB_STRING", "sqlite:///jobs.db")
            # Parse SQLite connection string (format: sqlite:///path/to/db.db)
            if db_string.startswith("sqlite:///"):
                db_path = db_string[10:]  # Remove "sqlite:///" prefix
            elif db_string.startswith("sqlite://"):
                db_path = db_string[9:]  # Remove "sqlite://" prefix
            else:
                db_path = db_string
        
        # Ensure absolute path
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(db_path)
        
        self.db_path = db_path
        self._init_database()
        logger.info(f"JobStorage initialized with SQLite database: {self.db_path}")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        return conn
    
    def _init_database(self):
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Create jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request_data TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    report_path TEXT,
                    briefs_available INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Add briefs_available column if it doesn't exist (migration for existing databases)
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN briefs_available INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                # Column already exists, ignore
                pass
            
            # Create job_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for better query performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON job_logs(job_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_logs_timestamp ON job_logs(timestamp)
            """)
            
            conn.commit()
            logger.debug("Database schema initialized")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
        finally:
            conn.close()
    
    def create_job(self, request_data: Dict) -> str:
        """
        Create a new job and return job_id.
        
        Args:
            request_data: Initial request data to store
            
        Returns:
            Unique job_id
        """
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO jobs (job_id, status, request_data, result, error, report_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                JobStatus.PENDING.value,
                json.dumps(request_data),
                None,
                None,
                None,
                now,
                now
            ))
            conn.commit()
            logger.info(f"Created job: {job_id}")
            return job_id
        except Exception as e:
            logger.error(f"Error creating job: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def get_job(self, job_id: str) -> Optional[Dict]:
        """
        Get job by ID.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job data dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM jobs WHERE job_id = ?
            """, (job_id,))
            
            row = cursor.fetchone()
            if row is None:
                return None
            
            # Convert row to dictionary
            # Handle briefs_available column (may not exist in older databases)
            briefs_available = 0
            try:
                briefs_available = row["briefs_available"] if row["briefs_available"] is not None else 0
            except (KeyError, IndexError):
                # Column doesn't exist, default to 0
                briefs_available = 0
            
            job = {
                "job_id": row["job_id"],
                "status": row["status"],
                "request_data": json.loads(row["request_data"]),
                "created_at": datetime.fromisoformat(row["created_at"]),
                "updated_at": datetime.fromisoformat(row["updated_at"]),
                "result": json.loads(row["result"]) if row["result"] else None,
                "error": row["error"],
                "report_path": row["report_path"],
                "briefs_available": bool(briefs_available)
            }
            
            return job
        except Exception as e:
            logger.error(f"Error getting job {job_id}: {e}")
            return None
        finally:
            conn.close()
    
    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        report_path: Optional[str] = None,
        briefs_available: Optional[bool] = None
    ) -> bool:
        """
        Update job status and optional result/error.
        
        Args:
            job_id: Job identifier
            status: New status
            result: Optional result data
            error: Optional error message
            report_path: Optional path to generated report
            briefs_available: Optional flag indicating if briefs/desk notes are available
            
        Returns:
            True if updated, False if job not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Build update query dynamically based on what's provided
            updates = ["status = ?", "updated_at = ?"]
            values = [status.value, datetime.now(timezone.utc).isoformat()]
            
            if result is not None:
                updates.append("result = ?")
                values.append(json.dumps(result))
            
            if error is not None:
                updates.append("error = ?")
                values.append(error)
            
            if report_path is not None:
                updates.append("report_path = ?")
                values.append(report_path)
            
            if briefs_available is not None:
                updates.append("briefs_available = ?")
                values.append(1 if briefs_available else 0)
            
            values.append(job_id)
            
            query = f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?"
            cursor.execute(query, values)
            
            if cursor.rowcount == 0:
                logger.warning(f"Job not found: {job_id}")
                return False
            
            conn.commit()
            logger.info(f"Updated job {job_id} to status: {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating job {job_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def list_jobs(self, limit: int = 100) -> List[Dict]:
        """
        List all jobs, sorted by creation time (newest first).
        
        Args:
            limit: Maximum number of jobs to return
            
        Returns:
            List of job dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM jobs
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            jobs = []
            for row in cursor.fetchall():
                # Handle briefs_available column (may not exist in older databases)
                briefs_available = 0
                try:
                    briefs_available = row["briefs_available"] if row["briefs_available"] is not None else 0
                except (KeyError, IndexError):
                    # Column doesn't exist, default to 0
                    briefs_available = 0
                
                job = {
                    "job_id": row["job_id"],
                    "status": row["status"],
                    "request_data": json.loads(row["request_data"]),
                    "created_at": datetime.fromisoformat(row["created_at"]),
                    "updated_at": datetime.fromisoformat(row["updated_at"]),
                    "result": json.loads(row["result"]) if row["result"] else None,
                    "error": row["error"],
                    "report_path": row["report_path"],
                    "briefs_available": bool(briefs_available)
                }
                jobs.append(job)
            
            return jobs
        except Exception as e:
            logger.error(f"Error listing jobs: {e}")
            return []
        finally:
            conn.close()
    
    def delete_job(self, job_id: str) -> bool:
        """
        Delete a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            
            if cursor.rowcount == 0:
                return False
            
            conn.commit()
            logger.info(f"Deleted job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting job {job_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def add_log(self, job_id: str, level: str, message: str) -> None:
        """
        Add a log entry for a job.
        
        Args:
            job_id: Job identifier
            level: Log level (INFO, WARNING, ERROR, etc.)
            message: Log message
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO job_logs (job_id, timestamp, level, message)
                VALUES (?, ?, ?, ?)
            """, (
                job_id,
                datetime.now(timezone.utc).isoformat(),
                level,
                message
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding log for job {job_id}: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def get_logs(self, job_id: str, since: Optional[datetime] = None) -> List[Dict]:
        """
        Get logs for a job, optionally filtered by timestamp.
        
        Args:
            job_id: Job identifier
            since: Optional datetime to get logs since (for incremental fetching)
            
        Returns:
            List of log dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            if since:
                since_iso = since.isoformat()
                cursor.execute("""
                    SELECT * FROM job_logs
                    WHERE job_id = ? AND timestamp > ?
                    ORDER BY timestamp ASC
                """, (job_id, since_iso))
            else:
                cursor.execute("""
                    SELECT * FROM job_logs
                    WHERE job_id = ?
                    ORDER BY timestamp ASC
                """, (job_id,))
            
            logs = []
            for row in cursor.fetchall():
                logs.append({
                    "timestamp": row["timestamp"],
                    "level": row["level"],
                    "message": row["message"]
                })
            
            return logs
        except Exception as e:
            logger.error(f"Error getting logs for job {job_id}: {e}")
            return []
        finally:
            conn.close()
    
    def clear_all(self) -> int:
        """
        Clear all jobs (for testing/cleanup).
        
        Returns:
            Number of jobs cleared
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs")
            count = cursor.fetchone()[0]
            
            cursor.execute("DELETE FROM jobs")
            conn.commit()
            
            logger.info(f"Cleared {count} jobs")
            return count
        except Exception as e:
            logger.error(f"Error clearing jobs: {e}")
            conn.rollback()
            return 0
        finally:
            conn.close()


# Global instance
job_storage = JobStorage()
