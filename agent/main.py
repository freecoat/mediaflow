"""Claqo Agent v0.1 (F1) — loop: heartbeat + poll coda + probe/checksum.

Avvio:  python -m agent.main
I volumi (id → mount_path) arrivano dal server a ogni heartbeat.
"""
from __future__ import annotations
import shutil
import time
import traceback

from agent import __version__
from agent.config import Config
from agent.client import ClaqoClient
from agent.browse import list_dir
from agent.preview import generate_preview, upload_preview
from agent.probe import build_probe_result, xxhash_file
from agent.transfer import run_transfer
from agent.watch import WatchState, scan_volume

CAPABILITIES = ["probe", "checksum", "scan", "browse", "preview", "transfer"]


def volume_stats(volumes: list[dict]) -> list[dict]:
    out = []
    for v in volumes:
        try:
            du = shutil.disk_usage(v["mount_path"])
            out.append({"volume_id": v["id"],
                        "total_gb": round(du.total / 1e9, 1),
                        "free_gb": round(du.free / 1e9, 1)})
        except OSError:
            pass
    return out


def handle_job(job: dict, volumes_by_id: dict, watch_states: dict,
               *, client=None) -> tuple[str, dict | None, str | None]:
    jtype, payload = job["type"], job.get("payload") or {}

    # Il ramo transfer gestisce i propri volume_id file-per-file:
    # non ha un volume_id top-level nel payload, quindi deve precedere il guard vol.
    if jtype == "transfer":
        try:
            return "done", run_transfer(payload, volumes_by_id), None
        except Exception as e:
            return "failed", None, f"{type(e).__name__}: {e}"

    vol = volumes_by_id.get(int(payload.get("volume_id") or 0))
    if vol is None:
        return "failed", None, f"volume_id {payload.get('volume_id')} sconosciuto all'agent"
    try:
        if jtype == "probe":
            return "done", build_probe_result(vol["mount_path"], payload["rel_path"]), None
        if jtype == "checksum":
            import os
            full = os.path.join(vol["mount_path"], payload["rel_path"])
            return "done", {"checksum_xxhash": xxhash_file(full)}, None
        if jtype == "browse":
            return "done", list_dir(vol["mount_path"], payload.get("rel_path") or ""), None
        if jtype == "preview":
            import tempfile
            with tempfile.TemporaryDirectory() as wd:
                path, meta = generate_preview(vol["mount_path"], payload["rel_path"],
                                              payload.get("tenant_name") or "Claqo", wd)
                uploaded = upload_preview(path, job_id=job["id"],
                                          upload_cfg=payload.get("upload") or {},
                                          client=client)
            return "done", {**meta, "uploaded": uploaded}, None
        if jtype == "scan":
            st = watch_states.setdefault(int(payload.get("volume_id") or 0), WatchState())
            items = scan_volume(vol["mount_path"], vol.get("watch_dirs") or [], st)
            return "done", {"volume_id": int(payload.get("volume_id") or 0), "items": items}, None
        return "failed", None, f"tipo job non supportato da agent v{__version__}: {jtype}"
    except Exception as e:
        return "failed", None, f"{type(e).__name__}: {e}"


def run():
    cfg = Config()
    client = ClaqoClient(cfg.server_url, cfg.token)
    volumes: list[dict] = []
    last_hb = 0.0
    watch_states: dict[int, WatchState] = {}
    print(f"[agent] v{__version__} → {cfg.server_url}")
    while True:
        try:
            now = time.monotonic()
            if now - last_hb >= cfg.heartbeat_seconds or not volumes:
                resp = client.heartbeat(__version__, CAPABILITIES,
                                        volume_stats(volumes))
                volumes = resp.get("volumes") or []
                last_hb = now
            vols_by_id = {v["id"]: v for v in volumes}
            job = client.claim()
            if job:
                print(f"[agent] job #{job['id']} {job['type']}")
                status, result, error = handle_job(job, vols_by_id, watch_states, client=client)
                client.post_result(job["id"], status, result, error)
                continue
        except Exception:
            traceback.print_exc()
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    run()
