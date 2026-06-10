"""HTTP client verso Claqo. Solo outbound, solo JSON."""
from __future__ import annotations
import requests


class ClaqoClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url
        self.s = requests.Session()
        self.s.headers["X-Agent-Token"] = token

    def heartbeat(self, version: str, capabilities: list, volumes: list) -> dict:
        r = self.s.post(f"{self.base}/agent-api/heartbeat", json={
            "version": version, "capabilities": capabilities, "volumes": volumes,
        }, timeout=30)
        r.raise_for_status()
        return r.json()

    def claim(self) -> dict | None:
        r = self.s.post(f"{self.base}/agent-api/jobs/claim", timeout=30)
        r.raise_for_status()
        return r.json().get("job")

    def post_result(self, job_id: int, status: str,
                    result: dict | None = None, error: str | None = None):
        r = self.s.post(f"{self.base}/agent-api/jobs/{job_id}/result", json={
            "status": status, "result": result, "error": error,
        }, timeout=60)
        r.raise_for_status()
        return r.json()
