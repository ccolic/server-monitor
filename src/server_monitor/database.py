"""Database models and operations."""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any

import aiosqlite
import asyncpg
import structlog
from pydantic import BaseModel

from .config import DatabaseConfig, DatabaseType

logger = structlog.get_logger(__name__)


class CheckStatus(str, Enum):
    """Check status values."""

    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"


class CheckResult(BaseModel):
    """Check result model."""

    endpoint_name: str
    check_type: str
    status: CheckStatus
    response_time: float | None = None
    error_message: str | None = None
    details: dict[str, Any] | None = None
    timestamp: datetime
    
    model_config = {
        "json_encoders": {datetime: lambda v: v.isoformat()}
    }


class DatabaseManager:
    """Database manager for storing check results."""

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._pool: Optional[Union[asyncpg.Pool, aiosqlite.Connection]] = None

    async def initialize(self) -> None:
        """Initialize database connection."""
        if self.config.type == DatabaseType.POSTGRESQL:
            await self._init_postgresql()
        elif self.config.type == DatabaseType.SQLITE:
            await self._init_sqlite()
        else:
            raise ValueError(f"Unsupported database type: {self.config.type}")

        await self._create_tables()
        logger.info("Database initialized", db_type=self.config.type)

    async def _init_postgresql(self) -> None:
        """Initialize PostgreSQL connection pool."""
        self._pool = await asyncpg.create_pool(
            self.config.url, min_size=2, max_size=10, command_timeout=60
        )

    async def _init_sqlite(self) -> None:
        """Initialize SQLite connection."""
        # For SQLite, we'll use a simple connection for now
        # In production, consider using aiosqlite with connection pooling
        pass

    async def _create_tables(self) -> None:
        """Create database tables."""
        if self.config.type == DatabaseType.POSTGRESQL:
            await self._create_postgresql_tables()
        elif self.config.type == DatabaseType.SQLITE:
            await self._create_sqlite_tables()

    async def _create_postgresql_tables(self) -> None:
        """Create PostgreSQL tables."""
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        create_table_sql = """
        CREATE TABLE IF NOT EXISTS check_results (
            id SERIAL PRIMARY KEY,
            endpoint_name VARCHAR(255) NOT NULL,
            check_type VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            response_time FLOAT,
            error_message TEXT,
            details JSONB,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_check_results_endpoint_timestamp 
        ON check_results(endpoint_name, timestamp DESC);
        
        CREATE INDEX IF NOT EXISTS idx_check_results_status 
        ON check_results(status);
        
        CREATE TABLE IF NOT EXISTS endpoint_status (
            endpoint_name VARCHAR(255) PRIMARY KEY,
            current_status VARCHAR(20) NOT NULL,
            last_success TIMESTAMP WITH TIME ZONE,
            last_failure TIMESTAMP WITH TIME ZONE,
            failure_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """

        async with self._pool.acquire() as conn:
            await conn.execute(create_table_sql)

    async def _create_sqlite_tables(self) -> None:
        """Create SQLite tables."""
        database_path = self.config.url.replace("sqlite:///", "")

        create_table_sql = """
        CREATE TABLE IF NOT EXISTS check_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_name TEXT NOT NULL,
            check_type TEXT NOT NULL,
            status TEXT NOT NULL,
            response_time REAL,
            error_message TEXT,
            details TEXT,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_check_results_endpoint_timestamp 
        ON check_results(endpoint_name, timestamp DESC);
        
        CREATE INDEX IF NOT EXISTS idx_check_results_status 
        ON check_results(status);
        
        CREATE TABLE IF NOT EXISTS endpoint_status (
            endpoint_name TEXT PRIMARY KEY,
            current_status TEXT NOT NULL,
            last_success TEXT,
            last_failure TEXT,
            failure_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """

        async with aiosqlite.connect(database_path) as conn:
            await conn.executescript(create_table_sql)
            await conn.commit()

    async def store_result(self, result: CheckResult) -> None:
        """Store a check result."""
        try:
            if self.config.type == DatabaseType.POSTGRESQL:
                await self._store_postgresql_result(result)
            elif self.config.type == DatabaseType.SQLITE:
                await self._store_sqlite_result(result)

            await self._update_endpoint_status(result)

        except Exception as e:
            logger.error(
                "Failed to store check result", error=str(e), result=result.dict()
            )
            raise

    async def _store_postgresql_result(self, result: CheckResult) -> None:
        """Store result in PostgreSQL."""
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        insert_sql = """
        INSERT INTO check_results (endpoint_name, check_type, status, response_time, 
                                 error_message, details, timestamp)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """

        async with self._pool.acquire() as conn:
            await conn.execute(
                insert_sql,
                result.endpoint_name,
                result.check_type,
                result.status.value,
                result.response_time,
                result.error_message,
                result.details,
                result.timestamp,
            )

    async def _store_sqlite_result(self, result: CheckResult) -> None:
        """Store result in SQLite."""
        database_path = self.config.url.replace("sqlite:///", "")

        insert_sql = """
        INSERT INTO check_results (endpoint_name, check_type, status, response_time, 
                                 error_message, details, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        async with aiosqlite.connect(database_path) as conn:
            await conn.execute(
                insert_sql,
                (
                    result.endpoint_name,
                    result.check_type,
                    result.status.value,
                    result.response_time,
                    result.error_message,
                    result.details,
                    result.timestamp.isoformat(),
                ),
            )
            await conn.commit()

    async def _update_endpoint_status(self, result: CheckResult) -> None:
        """Update endpoint status summary."""
        if self.config.type == DatabaseType.POSTGRESQL:
            await self._update_postgresql_endpoint_status(result)
        elif self.config.type == DatabaseType.SQLITE:
            await self._update_sqlite_endpoint_status(result)

    async def _update_postgresql_endpoint_status(self, result: CheckResult) -> None:
        """Update endpoint status in PostgreSQL."""
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        upsert_sql = """
        INSERT INTO endpoint_status (endpoint_name, current_status, last_success, 
                                   last_failure, failure_count, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (endpoint_name) 
        DO UPDATE SET
            current_status = EXCLUDED.current_status,
            last_success = CASE WHEN EXCLUDED.current_status = 'success' 
                              THEN EXCLUDED.last_success 
                              ELSE endpoint_status.last_success END,
            last_failure = CASE WHEN EXCLUDED.current_status != 'success' 
                              THEN EXCLUDED.last_failure 
                              ELSE endpoint_status.last_failure END,
            failure_count = CASE WHEN EXCLUDED.current_status = 'success' 
                               THEN 0
                               ELSE endpoint_status.failure_count + 1 END,
            updated_at = EXCLUDED.updated_at
        """

        last_success = (
            result.timestamp if result.status == CheckStatus.SUCCESS else None
        )
        last_failure = (
            result.timestamp if result.status != CheckStatus.SUCCESS else None
        )
        failure_count = 0 if result.status == CheckStatus.SUCCESS else 1

        async with self._pool.acquire() as conn:
            await conn.execute(
                upsert_sql,
                result.endpoint_name,
                result.status.value,
                last_success,
                last_failure,
                failure_count,
                datetime.now(),
            )

    async def _update_sqlite_endpoint_status(self, result: CheckResult) -> None:
        """Update endpoint status in SQLite."""
        database_path = self.config.url.replace("sqlite:///", "")

        # SQLite doesn't have native UPSERT like PostgreSQL, so we'll use INSERT OR REPLACE
        upsert_sql = """
        INSERT OR REPLACE INTO endpoint_status (
            endpoint_name, current_status, last_success, last_failure, 
            failure_count, updated_at
        )
        VALUES (
            ?, ?, 
            CASE WHEN ? = 'success' THEN ? ELSE 
                (SELECT last_success FROM endpoint_status WHERE endpoint_name = ?) END,
            CASE WHEN ? != 'success' THEN ? ELSE 
                (SELECT last_failure FROM endpoint_status WHERE endpoint_name = ?) END,
            CASE WHEN ? = 'success' THEN 0 ELSE 
                COALESCE((SELECT failure_count FROM endpoint_status WHERE endpoint_name = ?), 0) + 1 END,
            ?
        )
        """

        async with aiosqlite.connect(database_path) as conn:
            await conn.execute(
                upsert_sql,
                (
                    result.endpoint_name,
                    result.status.value,
                    result.status.value,
                    result.timestamp.isoformat(),
                    result.endpoint_name,
                    result.status.value,
                    result.timestamp.isoformat(),
                    result.endpoint_name,
                    result.status.value,
                    result.endpoint_name,
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()

    async def get_endpoint_status(self, endpoint_name: str) -> Optional[Dict[str, Any]]:
        """Get current status for an endpoint."""
        if self.config.type == DatabaseType.POSTGRESQL:
            return await self._get_postgresql_endpoint_status(endpoint_name)
        elif self.config.type == DatabaseType.SQLITE:
            return await self._get_sqlite_endpoint_status(endpoint_name)
        return None

    async def _get_postgresql_endpoint_status(
        self, endpoint_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get endpoint status from PostgreSQL."""
        if not self._pool:
            raise RuntimeError("Database pool not initialized")

        select_sql = """
        SELECT endpoint_name, current_status, last_success, last_failure, 
               failure_count, updated_at
        FROM endpoint_status
        WHERE endpoint_name = $1
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(select_sql, endpoint_name)
            if row:
                return dict(row)
            return None

    async def _get_sqlite_endpoint_status(
        self, endpoint_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get endpoint status from SQLite."""
        database_path = self.config.url.replace("sqlite:///", "")

        select_sql = """
        SELECT endpoint_name, current_status, last_success, last_failure, 
               failure_count, updated_at
        FROM endpoint_status
        WHERE endpoint_name = ?
        """

        async with aiosqlite.connect(database_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(select_sql, (endpoint_name,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None

    async def close(self) -> None:
        """Close database connections."""
        if self.config.type == DatabaseType.POSTGRESQL and self._pool:
            await self._pool.close()

        logger.info("Database connections closed")
