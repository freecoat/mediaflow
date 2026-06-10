"""Config da ENV o file claqo-agent.json nella cwd.

ENV: CLAQO_URL, CLAQO_AGENT_TOKEN, CLAQO_POLL_SECONDS (default 5),
CLAQO_HEARTBEAT_SECONDS (default 30).
"""
from __future__ import annotations
import json
import os


class Config:
    def __init__(self):
        file_cfg = {}
        if os.path.isfile("claqo-agent.json"):
            with open("claqo-agent.json", encoding="utf-8") as f:
                file_cfg = json.load(f)
        self.server_url = (os.environ.get("CLAQO_URL")
                           or file_cfg.get("server_url") or "").rstrip("/")
        self.token = os.environ.get("CLAQO_AGENT_TOKEN") or file_cfg.get("token") or ""
        self.poll_seconds = int(os.environ.get("CLAQO_POLL_SECONDS")
                                or file_cfg.get("poll_seconds") or 5)
        self.heartbeat_seconds = int(os.environ.get("CLAQO_HEARTBEAT_SECONDS")
                                     or file_cfg.get("heartbeat_seconds") or 30)
        if not self.server_url or not self.token:
            raise SystemExit("Config mancante: CLAQO_URL e CLAQO_AGENT_TOKEN "
                             "(env o claqo-agent.json)")
