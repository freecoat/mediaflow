"""F1 (spec 2026-06-10) — API per Claqo Agent (facility-side).

Auth: header X-Agent-Token (sha256 lookup su AgentNode). SOLO outbound
dall'agent: heartbeat, claim job, push risultato. Nessun byte di
contenuto transita: solo JSON metadata.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import AgentNode, AgentJob, AgentJobType, StorageVolume
from app.services.agent_queue import (
    hash_agent_token, claim_next_job, complete_job, fail_job,
)
from app.services.asset_registry import create_proposal_from_probe
from app.services.clock import now_utc

router = APIRouter(prefix="/agent-api", tags=["agent"])


def get_agent(x_agent_token: str = Header(...),
              db: Session = Depends(get_db)) -> AgentNode:
    agent = db.execute(
        select(AgentNode).where(
            AgentNode.auth_token_hash == hash_agent_token(x_agent_token),
            AgentNode.is_active.is_(True))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=401, detail="agent token non valido")
    return agent


class HeartbeatIn(BaseModel):
    version: Optional[str] = None
    capabilities: Optional[list] = None
    volumes: Optional[list] = None


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, agent: AgentNode = Depends(get_agent),
              db: Session = Depends(get_db)):
    agent.last_heartbeat_at = now_utc()
    if body.version:
        agent.version = body.version
    if body.capabilities is not None:
        agent.capabilities = body.capabilities
    for vs in body.volumes or []:
        vol = db.get(StorageVolume, int(vs.get("volume_id") or 0))
        if vol is not None and vol.tenant_id == agent.tenant_id:
            vol.total_gb = vs.get("total_gb")
            vol.free_gb = vs.get("free_gb")
    db.commit()
    vols = db.execute(
        select(StorageVolume).where(StorageVolume.tenant_id == agent.tenant_id,
                                    StorageVolume.is_active.is_(True))
    ).scalars().all()
    return {"ok": True, "volumes": [
        {"id": v.id, "name": v.name, "mount_path": v.mount_path,
         "watch_dirs": v.watch_dirs or [], "read_only": v.read_only}
        for v in vols
    ]}


@router.post("/jobs/claim")
def claim(agent: AgentNode = Depends(get_agent), db: Session = Depends(get_db)):
    job = claim_next_job(db, agent)
    db.commit()
    if job is None:
        return {"job": None}
    return {"job": {"id": job.id, "type": job.type.value, "payload": job.payload}}


class ResultIn(BaseModel):
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None


def process_job_result(db: Session, job: AgentJob, *, status: str,
                       result: Optional[dict], error: Optional[str] = None):
    """Applica l'esito del job. Probe done → crea proposta asset.
    Ritorna l'Asset creato (o None). Estratta dal route handler per testabilità."""
    if status == "failed":
        fail_job(db, job, error or "errore agent non specificato")
        return None
    complete_job(db, job, result or {})
    if job.type == AgentJobType.probe and result:
        volume_id = int((job.payload or {}).get("volume_id") or 0)
        asset = create_proposal_from_probe(
            db, tenant_id=job.tenant_id, volume_id=volume_id, probe=result,
            user_id=job.requested_by_user_id or 1,
            registered_via="manual_path")
        job.asset_id = asset.id
        db.flush()
        return asset
    return None


@router.post("/jobs/{job_id}/result")
def post_result(job_id: int, body: ResultIn,
                agent: AgentNode = Depends(get_agent),
                db: Session = Depends(get_db)):
    job = db.get(AgentJob, job_id)
    if job is None or job.tenant_id != agent.tenant_id or job.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="job non trovato")
    asset = process_job_result(db, job, status=body.status,
                               result=body.result, error=body.error)
    db.commit()
    return {"ok": True, "asset_id": asset.id if asset else None}
