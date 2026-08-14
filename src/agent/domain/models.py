"""SQLAlchemy database models for multi-tenant product features."""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from agent.core.db import Base


class Tenant(Base):
    """A tenant represents an isolated customer workspace."""

    __tablename__ = "tenants"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """An authenticated user belonging to a tenant."""

    __tablename__ = "users"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # Viewer, QA Engineer, QA Manager, Admin
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    """An execution run of the QA Agent."""

    __tablename__ = "runs"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    requester_id = Column(String, ForeignKey("users.id"), nullable=True)
    goal = Column(String, nullable=False)
    status = Column(
        String, nullable=False, index=True
    )  # queued, running, completed, failed, blocked, cancelled
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    findings_count = Column(Integer, default=0)
    defect_count = Column(Integer, default=0)


class Finding(Base):
    """A finding or defect identified during a run."""

    __tablename__ = "findings"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("runs.id"), nullable=False, index=True)
    capability = Column(String, nullable=False)
    description = Column(String, nullable=False)
    is_defect = Column(Boolean, nullable=False)
    severity = Column(String, nullable=True)
    evidence = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
