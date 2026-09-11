#!/usr/bin/env python
"""Local services and prerequisites checker.

Validates:
1. PostgreSQL host/port connectivity, database existence, credentials, and pgvector extension.
2. Redis host/port connectivity and PING response.
3. API port (8000) and Frontend port (5173) availability.
4. Playwright Chromium browser installation.

Never starts Docker. Provides actionable Windows remediation instructions for missing dependencies.
"""

import asyncio
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

# Ensure src is in python path
repo_root = Path(__file__).resolve().parent.parent
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from agent.core.config import get_settings


def check_port_available(host: str, port: int) -> bool:
    """Return True if port is free to bind, False if occupied."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            result = s.connect_ex((host, port))
            return result != 0
    except Exception:
        return True


async def check_redis(redis_url: str) -> tuple[bool, str]:
    """Test Redis connection and PING response."""
    import redis.asyncio as aioredis

    try:
        client = aioredis.from_url(redis_url, socket_connect_timeout=3.0)
        try:
            pong = await client.ping()
            if pong:
                return True, "Redis responded to PING"
            return False, "Redis did not respond with PONG"
        finally:
            await client.aclose()
    except Exception as e:
        return False, str(e)


async def check_postgres(postgres_url: str) -> tuple[bool, bool, str]:
    """Test PostgreSQL connectivity, credentials, database, and pgvector extension.

    Returns: (db_ok, pgvector_ok, message)
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    try:
        engine = create_async_engine(postgres_url, poolclass=NullPool, connect_args={"timeout": 5})
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                # Check pgvector
                res = await conn.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
                has_vector = res.scalar_one_or_none() is not None
                if not has_vector:
                    # Try creating extension
                    try:
                        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                        await conn.commit()
                        has_vector = True
                    except Exception:
                        pass
                return True, has_vector, "PostgreSQL connection and database verified"
        finally:
            await engine.dispose()
    except Exception as e:
        return False, False, str(e)


async def check_playwright_chromium() -> tuple[bool, str]:
    """Verify Playwright Chromium browser is installed."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser_path = p.chromium.executable_path
            if browser_path and Path(browser_path).exists():
                return True, f"Playwright Chromium found at {browser_path}"
            return False, "Chromium executable path does not exist"
    except Exception as e:
        return False, str(e)


async def main() -> int:
    settings = get_settings()
    overall_ok = True

    print("=" * 65)
    print("  ServiceNow UAT Agent - Local Services & Prerequisites Check")
    print("=" * 65)

    # 1. PostgreSQL Check
    pg_url = settings.domain.postgres_url
    parsed_pg = urlparse(settings.domain.asyncpg_dsn)
    pg_host = parsed_pg.hostname or "127.0.0.1"
    pg_port = parsed_pg.port or 5432
    pg_db = parsed_pg.path.lstrip("/") or "servicenow_qa"

    print(f"\n[1/4] Checking PostgreSQL on {pg_host}:{pg_port} (DB: {pg_db})...")
    pg_ok, pgvector_ok, pg_msg = await check_postgres(pg_url)

    if pg_ok:
        print(f"  [PASS] PostgreSQL: {pg_msg}")
        if pgvector_ok:
            print("  [PASS] pgvector extension: active and available")
        else:
            print("  [WARN] pgvector extension: NOT found in database")
            print("         To install pgvector on Windows:")
            print("         - Precompiled binaries: https://github.com/pgvector/pgvector#windows")
            print("         - Or in psql superuser session: CREATE EXTENSION vector;")
            # Note: We treat missing pgvector as warning/failure based on strictness
    else:
        overall_ok = False
        print(f"  [FAIL] PostgreSQL: {pg_msg}")
        print("         Remediation:")
        print(f"         1. Ensure PostgreSQL is installed and running on {pg_host}:{pg_port}.")
        print("            Download: https://www.postgresql.org/download/windows/")
        print("            PowerShell: Start-Service postgresql*")
        print(f"         2. Ensure database '{pg_db}' exists.")
        print(f"            Command: createdb -U {parsed_pg.username or 'postgres'} {pg_db}")
        print("         3. Ensure credentials in .env.local match your local PostgreSQL.")

    # 2. Redis Check
    redis_url = settings.session.redis_url
    parsed_redis = urlparse(redis_url)
    redis_host = parsed_redis.hostname or "127.0.0.1"
    redis_port = parsed_redis.port or 6379

    print(f"\n[2/4] Checking Redis on {redis_host}:{redis_port}...")
    redis_ok, redis_msg = await check_redis(redis_url)

    if redis_ok:
        print(f"  [PASS] Redis: {redis_msg}")
    else:
        overall_ok = False
        print(f"  [FAIL] Redis: {redis_msg}")
        print("         Remediation:")
        print(f"         1. Ensure Redis is running on {redis_host}:{redis_port}.")
        print("            Options for Windows:")
        print("            - Memurai (Redis for Windows): https://www.memurai.com/")
        print("            - WSL Redis: wsl sudo service redis-server start")
        print("         2. Ensure REDIS_URL in .env.local matches your setup.")

    # 3. Port Availability Checks
    print("\n[3/4] Checking local port availability (8000 for API, 5173 for Frontend)...")
    api_free = check_port_available("127.0.0.1", 8000)
    fe_free = check_port_available("127.0.0.1", 5173)

    if api_free:
        print("  [PASS] Port 8000 (API): available")
    else:
        overall_ok = False
        print("  [FAIL] Port 8000 is currently occupied. Stop the conflicting process.")

    if fe_free:
        print("  [PASS] Port 5173 (Frontend): available")
    else:
        overall_ok = False
        print("  [FAIL] Port 5173 is currently occupied. Stop the conflicting process.")

    # 4. Playwright Chromium Check
    print("\n[4/4] Checking Playwright Chromium browser...")
    pw_ok, pw_msg = await check_playwright_chromium()
    if pw_ok:
        print(f"  [PASS] {pw_msg}")
    else:
        overall_ok = False
        print(f"  [FAIL] Playwright Chromium: {pw_msg}")
        print("         Remediation: Run 'playwright install chromium'")

    print("\n" + "=" * 65)
    if overall_ok and pgvector_ok:
        print("  All local services and prerequisites are READY!")
        print("=" * 65)
        return 0
    elif overall_ok and not pgvector_ok:
        print("  Basic connectivity passed, but pgvector is required for RAG/memory.")
        print("=" * 65)
        return 1
    else:
        print("  Some required local services or prerequisites are MISSING.")
        print("  See instructions above to configure prerequisites before starting.")
        print("=" * 65)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
