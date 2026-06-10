"""F1 — coda AgentJob: token, enqueue, claim FIFO tenant-scoped, complete/fail."""
import pytest

from app.models.models import (
    Tenant, AgentNode, AgentJob, AgentJobType, AgentJobStatus,
)
from app.services.agent_queue import (
    generate_agent_token, hash_agent_token,
    enqueue_job, claim_next_job, complete_job, fail_job,
)


def _setup(db, tid=1):
    db.add(Tenant(id=tid, name=f"T{tid}", slug=f"t{tid}"))
    db.flush()
    plain, h = generate_agent_token()
    agent = AgentNode(tenant_id=tid, name="ag", auth_token_hash=h)
    db.add(agent)
    db.flush()
    return agent, plain


def test_token_roundtrip():
    plain, h = generate_agent_token()
    assert len(plain) >= 40
    assert hash_agent_token(plain) == h
    assert len(h) == 64


def test_enqueue_and_claim_fifo(db):
    agent, _ = _setup(db)
    j1 = enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={"p": 1})
    j2 = enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={"p": 2})
    got = claim_next_job(db, agent)
    assert got.id == j1.id
    assert got.status == AgentJobStatus.claimed
    assert got.agent_id == agent.id
    assert got.claimed_at is not None
    got2 = claim_next_job(db, agent)
    assert got2.id == j2.id


def test_claim_tenant_isolation(db):
    agent1, _ = _setup(db, tid=1)
    agent2, _ = _setup(db, tid=2)
    enqueue_job(db, tenant_id=2, type=AgentJobType.scan, payload={})
    assert claim_next_job(db, agent1) is None
    assert claim_next_job(db, agent2) is not None


def test_claim_respects_agent_pinning(db):
    agent, _ = _setup(db)
    other = AgentNode(tenant_id=1, name="ag2", auth_token_hash="c" * 64)
    db.add(other)
    db.flush()
    enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={}, agent_id=other.id)
    assert claim_next_job(db, agent) is None
    assert claim_next_job(db, other) is not None


def test_complete_and_fail(db):
    agent, _ = _setup(db)
    j = enqueue_job(db, tenant_id=1, type=AgentJobType.probe, payload={})
    claim_next_job(db, agent)
    complete_job(db, j, {"ok": True})
    assert j.status == AgentJobStatus.done
    assert j.result == {"ok": True}
    assert j.finished_at is not None

    j2 = enqueue_job(db, tenant_id=1, type=AgentJobType.checksum, payload={})
    claim_next_job(db, agent)
    fail_job(db, j2, "ffprobe not found")
    assert j2.status == AgentJobStatus.failed
    assert "ffprobe" in j2.error
