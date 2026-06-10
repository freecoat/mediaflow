"""F1 (spec 2026-06-10) — Coda comandi agent: token, enqueue, claim, esiti.

Claim = FIFO tenant-scoped: job più vecchio `queued` con agent_id NULL
oppure pinnato all'agent chiamante. Niente lock distribuito: SQLite
single-writer basta per N agent piccoli (1-2 per facility).
"""
from __future__ import annotations
import hashlib
import secrets
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models.models import AgentJob, AgentJobStatus, AgentJobType, AgentNode
from app.services.clock import now_utc


def generate_agent_token() -> tuple[str, str]:
    """Ritorna (token_plain, sha256_hex). Plain mostrato UNA volta in UI."""
    plain = secrets.token_urlsafe(32)
    return plain, hash_agent_token(plain)


def hash_agent_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def enqueue_job(db: Session, *, tenant_id: int, type: AgentJobType,
                payload: Optional[dict] = None, agent_id: Optional[int] = None,
                requested_by_user_id: Optional[int] = None,
                asset_id: Optional[int] = None,
                physical_asset_id: Optional[int] = None) -> AgentJob:
    job = AgentJob(tenant_id=tenant_id, type=type, payload=payload or {},
                   agent_id=agent_id, requested_by_user_id=requested_by_user_id,
                   asset_id=asset_id, physical_asset_id=physical_asset_id)
    db.add(job)
    db.flush()
    return job


def claim_next_job(db: Session, agent: AgentNode) -> Optional[AgentJob]:
    job = db.execute(
        select(AgentJob)
        .where(AgentJob.tenant_id == agent.tenant_id,
               AgentJob.status == AgentJobStatus.queued,
               or_(AgentJob.agent_id.is_(None), AgentJob.agent_id == agent.id))
        .order_by(AgentJob.id)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = AgentJobStatus.claimed
    job.agent_id = agent.id
    job.claimed_at = now_utc()
    db.flush()
    return job


def complete_job(db: Session, job: AgentJob, result: dict) -> AgentJob:
    job.status = AgentJobStatus.done
    job.result = result
    job.progress = 100
    job.finished_at = now_utc()
    db.flush()
    return job


def fail_job(db: Session, job: AgentJob, error: str) -> AgentJob:
    job.status = AgentJobStatus.failed
    job.error = (error or "")[:4000]
    job.finished_at = now_utc()
    db.flush()
    return job
