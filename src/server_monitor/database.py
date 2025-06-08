"""Database models and operations."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
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

    def model_dump_json(self, **kwargs: Any) -> str:
        """Custom JSON serialization with datetime handling."""
        return super().model_dump_json(
            default=lambda obj: obj.isoformat() if isinstance(obj, datetime) else None,
            **kwargs,
        )


class DatabaseManager:
    """Database manager for storing check results."""

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._pool: asyncpg.Pool[Any] | aiosqlite.Connection | None = None

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
        try:
            self._pool = await asyncpg.create_pool(
                self.config.url,
                min_size=2,
                max_size=10,
                command_timeout=60,
                server_settings={
                    "jit": "off"  # Disable JIT for better connection reliability
                },
            )
            logger.info("PostgreSQL connection pool initialized")
        except Exception as e:
            logger.error("Failed to initialize PostgreSQL pool", error=str(e))
            raise

    async def _init_sqlite(self) -> None:
        """Initialize SQLite connection."""
        try:
            # Create database file if it doesn't exist
            import aiosqlite

            self._pool = await aiosqlite.connect(
                self.config.database or "monitor.db", timeout=30.0
            )
            # Enable WAL mode for better concurrent access
            await self._pool.execute("PRAGMA journal_mode=WAL")
            await self._pool.execute("PRAGMA synchronous=NORMAL")
            await self._pool.commit()
            logger.info("SQLite connection initialized", database=self.config.database)
        except Exception as e:
            logger.error("Failed to initialize SQLite connection", error=str(e))
            raise

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

        if self.config.type == DatabaseType.POSTGRESQL:
            async with self._pool.acquire() as conn:  # type: ignore
                await conn.execute(create_table_sql)
        else:
            # fallback for SQLite, should not happen here
            pass

    async def _create_sqlite_tables(self) -> None:
        """Create SQLite tables."""
        database_path = (
            self.config.url.replace("sqlite:///", "")
            if self.config.url is not None
            else ""
        )

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
        # Convert dict to JSON string for storage
        details_json = (
            json.dumps(result.details) if result.details is not None else None
        )
        insert_sql = """
        INSERT INTO check_results (
            endpoint_name, check_type, status, response_time, error_message, details, timestamp
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        if self.config.type == DatabaseType.POSTGRESQL:
            async with self._pool.acquire() as conn:  # type: ignore
                await conn.execute(
                    insert_sql,
                    result.endpoint_name,
                    result.check_type,
                    result.status.value,
                    result.response_time,
                    result.error_message,
                    details_json,
                    result.timestamp,
                )
        else:
            # fallback for SQLite, should not happen here
            pass

    async def _store_sqlite_result(self, result: CheckResult) -> None:
        """Store result in SQLite."""
        database_path = (
            self.config.url.replace("sqlite:///", "")
            if self.config.url is not None
            else ""
        )

        insert_sql = """
        INSERT INTO check_results (endpoint_name, check_type, status, response_time,
                                 error_message, details, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        # Convert dict to JSON string for storage
        details_json = (
            json.dumps(result.details) if result.details is not None else None
        )

        async with aiosqlite.connect(database_path) as conn:
            await conn.execute(
                insert_sql,
                (
                    result.endpoint_name,
                    result.check_type,
                    result.status.value,
                    result.response_time,
                    result.error_message,
                    details_json,
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
        upsert_sql = """
        INSERT INTO endpoint_status (
            endpoint_name, current_status, last_success, last_failure, failure_count, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (endpoint_name) DO UPDATE SET
            current_status = EXCLUDED.current_status,
            last_success = EXCLUDED.last_success,
            last_failure = EXCLUDED.last_failure,
            failure_count = EXCLUDED.failure_count,
            updated_at = EXCLUDED.updated_at
        """
        last_success = (
            result.timestamp if result.status == CheckStatus.SUCCESS else None
        )
        last_failure = (
            result.timestamp if result.status != CheckStatus.SUCCESS else None
        )
        failure_count = 0 if result.status == CheckStatus.SUCCESS else 1
        if self.config.type == DatabaseType.POSTGRESQL:
            async with self._pool.acquire() as conn:  # type: ignore
                await conn.execute(
                    upsert_sql,
                    result.endpoint_name,
                    result.status.value,
                    last_success,
                    last_failure,
                    failure_count,
                    datetime.now(),
                )
        else:
            # fallback for SQLite, should not happen here
            pass

    async def _update_sqlite_endpoint_status(self, result: CheckResult) -> None:
        """Update endpoint status in SQLite."""
        database_path = (
            self.config.url.replace("sqlite:///", "")
            if self.config.url is not None
            else ""
        )

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

    async def get_endpoint_status(self, endpoint_name: str) -> dict[str, Any] | None:
        """Get current status for an endpoint."""
        if self.config.type == DatabaseType.POSTGRESQL:
            return await self._get_postgresql_endpoint_status(endpoint_name)
        elif self.config.type == DatabaseType.SQLITE:
            return await self._get_sqlite_endpoint_status(endpoint_name)
        return None

    async def _get_postgresql_endpoint_status(
        self, endpoint_name: str
    ) -> dict[str, Any] | None:
        """Get endpoint status from PostgreSQL."""
        select_sql = """
        SELECT endpoint_name, current_status, last_success, last_failure,
               failure_count, updated_at
        FROM endpoint_status
        WHERE endpoint_name = $1
        """
        if self.config.type == DatabaseType.POSTGRESQL:
            async with self._pool.acquire() as conn:  # type: ignore
                row = await conn.fetchrow(select_sql, endpoint_name)
                if row:
                    return dict(row)
                return None
        else:
            # fallback for SQLite, should not happen here
            return None

    async def _get_sqlite_endpoint_status(
        self, endpoint_name: str
    ) -> dict[str, Any] | None:
        """Get endpoint status from SQLite."""
        database_path = (
            self.config.url.replace("sqlite:///", "")
            if self.config.url is not None
            else ""
        )

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
        try:
            if self._pool:
                if self.config.type == DatabaseType.POSTGRESQL:
                    # Close PostgreSQL pool
                    await self._pool.close()
                    logger.info("PostgreSQL connection pool closed")
                elif self.config.type == DatabaseType.SQLITE:
                    # Close SQLite connection
                    await self._pool.close()
                    logger.info("SQLite connection closed")
                self._pool = None
        except Exception as e:
            logger.error("Error closing database connections", error=str(e))
