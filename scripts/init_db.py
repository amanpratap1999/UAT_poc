import asyncio
import os
import sys
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

# Ensure we can import from agent
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from agent.core.db import Base, engine
from agent.domain.models import User, Tenant
from agent.api.v1.auth import get_password_hash

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

        # Create user if not exists
        user_result = await session.execute(select(User).where(User.username == username))
        user = user_result.scalar_one_or_none()

        if not user:
            hashed_password = get_password_hash(password)
            user_id = str(uuid.uuid4())
            user = User(
                id=user_id,
                tenant_id=default_tenant_id,
                username=username,
                hashed_password=hashed_password,
                role="QA Manager"
            )
            session.add(user)
            await session.commit()
            print(f"Created QA user: {username} (Role: QA Manager)")
        else:
            print(f"QA user {username} already exists.")

if __name__ == "__main__":
    asyncio.run(init_db())
