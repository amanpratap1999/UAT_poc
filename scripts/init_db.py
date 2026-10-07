import asyncio
import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Ensure we can import from agent
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from agent.api.v1.auth import get_password_hash
from agent.core.db import Base, engine
from agent.domain.models import Tenant, User


async def init_db():
    print("Initializing database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database schema created successfully.")

    username = os.environ.get("QA_ADMIN_USERNAME")
    password = os.environ.get("QA_ADMIN_PASSWORD")

    if not username or not password:
        print("Error: QA_ADMIN_USERNAME or QA_ADMIN_PASSWORD not set in environment.", file=sys.stderr)
        sys.exit(1)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Create default tenant if not exists
        default_tenant_id = "tenant-0"
        tenant_result = await session.execute(select(Tenant).where(Tenant.id == default_tenant_id))
        tenant = tenant_result.scalar_one_or_none()

        if not tenant:
            tenant = Tenant(id=default_tenant_id, name="Default QA Tenant")
            session.add(tenant)
            await session.commit()
            print(f"Created default tenant: {default_tenant_id}")
        else:
            print(f"Tenant {default_tenant_id} already exists.")

        # Seed ONLY the configured QA_ADMIN_USERNAME (audit issue I7).
        # The previous implementation also seeded a hard-coded "admin" username
        # with role="Admin" using the same QA_ADMIN_PASSWORD — a backdoor
        # account that granted full Admin access to anyone who knew the
        # configured admin password, regardless of QA_ADMIN_USERNAME.
        # If an operator genuinely wants a user literally named "admin",
        # they should set QA_ADMIN_USERNAME=admin explicitly.
        users_to_sync = [username]
        # The configured admin user gets role="Admin" so they can actually
        # access Admin-only endpoints (the prior role="QA Manager" was
        # pre-existing behavior left for the hard-coded "admin" to override).
        admin_role = os.environ.get("QA_ADMIN_ROLE", "Admin")
        hashed_password = get_password_hash(password)

        for u in users_to_sync:
            user_result = await session.execute(select(User).where(User.username == u))
            existing_user = user_result.scalar_one_or_none()
            if not existing_user:
                new_user = User(
                    id=str(uuid.uuid4()),
                    tenant_id=default_tenant_id,
                    username=u,
                    hashed_password=hashed_password,
                    role=admin_role,
                )
                session.add(new_user)
                await session.commit()
                print(f"Created user: {u} (role: {admin_role})")
            else:
                existing_user.hashed_password = hashed_password
                await session.commit()
                print(f"Updated password for: {u}")

        # Defensive: warn loudly if a legacy "admin" backdoor account still
        # exists in the database so operators know to delete it manually.
        legacy_admin_result = await session.execute(
            select(User).where(User.username == "admin")
        )
        legacy_admin = legacy_admin_result.scalar_one_or_none()
        if legacy_admin is not None:
            print(
                "WARNING: A legacy user named 'admin' still exists in the "
                "database. This account was created by a prior version of "
                "init_db.py as a hard-coded backdoor. Delete it manually "
                "if it is not a legitimately intended account: "
                "DELETE FROM users WHERE username = 'admin';",
                file=sys.stderr,
            )

if __name__ == "__main__":
    asyncio.run(init_db())
