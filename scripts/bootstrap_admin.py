"""One-time admin bootstrap CLI script.

Safely initializes or updates an administrative user in PostgreSQL with bcrypt password hashing.

Usage:
    python scripts/bootstrap_admin.py --username admin --password MySecurePassword123!
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from agent.api.v1.auth import get_password_hash
from agent.core.db import AsyncSessionLocal
from agent.domain.models import User


async def bootstrap_admin(username: str, password: str, tenant_id: str = "default", role: str = "admin") -> int:
    if not username or not password:
        print("[!] Error: Username and password must not be empty.", file=sys.stderr)
        return 1

    if len(password) < 8:
        print("[!] Error: Password must be at least 8 characters.", file=sys.stderr)
        return 1

    print(f"[*] Bootstrapping user '{username}' (role: {role}, tenant: {tenant_id})...")

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.username == username))
            existing_user = result.scalars().first()

            hashed = get_password_hash(password)

            if existing_user:
                print(f"[*] User '{username}' already exists. Updating credentials and role...")
                existing_user.hashed_password = hashed
                existing_user.role = role
                existing_user.tenant_id = tenant_id
            else:
                user = User(
                    username=username,
                    hashed_password=hashed,
                    role=role,
                    tenant_id=tenant_id,
                )
                session.add(user)

            await session.commit()
            print(f"[+] Successfully provisioned user '{username}'.")
            return 0
        except Exception as e:
            await session.rollback()
            print(f"[!] Database operation failed: {e}", file=sys.stderr)
            return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap admin user in ServiceNow UAT Engine")
    parser.add_argument("--username", required=True, help="Administrative username")
    parser.add_argument("--password", required=True, help="Administrative password")
    parser.add_argument("--tenant-id", default="default", help="Tenant identifier (default: default)")
    parser.add_argument("--role", default="admin", help="User role (default: admin)")

    args = parser.parse_args()

    exit_code = asyncio.run(
        bootstrap_admin(
            username=args.username,
            password=args.password,
            tenant_id=args.tenant_id,
            role=args.role,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
