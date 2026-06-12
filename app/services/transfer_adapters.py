"""F5 — Adapter interface per i tool di transfer digitale dalla facility.

Ogni driver implementa TransferAdapter. Il registry ADAPTERS è il punto di
estensione per nuovi driver: aggiungere qui Media Shuttle, S3, Netflix Backlot.

Driver v1:
  - manual  (mode manual): l'operatore esegue con il tool che vuole e chiude
                            l'ordine con esito + link. Nessun AgentJob.
  - aspera  (mode agent):  l'agent esegue `ascp` e riporta l'esito.
                            Credenziali SOLO env agent-side (mai payload/DB).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.models import TransferOrder


class TransferAdapter:
    """Classe base per driver di transfer. Subclass devono definire key/label/mode."""

    key: str = ""
    label: str = ""
    mode: str = ""  # "manual" | "agent"

    def build_job_payload(self, order: "TransferOrder", files: list[dict]) -> dict:
        """Costruisce il payload JSON per l'AgentJob.

        Args:
            order: istanza TransferOrder con destination e asset_ids.
            files: lista di {volume_id, rel_path} risolti dagli Asset registrati.

        Returns:
            dict da salvare come AgentJob.payload.

        Raises:
            NotImplementedError: per driver mode=manual che non usano AgentJob.
        """
        raise NotImplementedError(
            f"Adapter '{self.key}' (mode={self.mode}) non supporta build_job_payload."
        )


class ManualAdapter(TransferAdapter):
    """Driver manuale: nessun AgentJob, l'operatore esegue con il tool preferito
    (Shuttle, MASV, Backlot web, S3 console, ...) e chiude l'ordine con esito+link."""

    key = "manual"
    label = "Manuale"
    mode = "manual"

    # build_job_payload NON è implementato: ereditata da base → NotImplementedError


class AsperaAdapter(TransferAdapter):
    """Driver Aspera ascp (agent-driven). Destination = formato ascp user@host:/path.
    Credenziali (ASPERA_SSH_KEY_PATH, ASPERA_EXTRA_ARGS) lette dall'agent via env,
    mai incluse nel payload o nel DB."""

    key = "aspera"
    label = "Aspera (ascp)"
    mode = "agent"

    def build_job_payload(self, order: "TransferOrder", files: list[dict]) -> dict:
        """Ritorna il payload per l'AgentJob di tipo transfer.

        Shape: {tool: "aspera", files: [{volume_id, rel_path}], destination: str, extra_args: []}
        """
        return {
            "tool": "aspera",
            "files": files,
            "destination": order.destination,
            "extra_args": [],
        }


# Registry principale — driver futuri shuttle/s3/backlot si aggiungono qui.
ADAPTERS: dict[str, TransferAdapter] = {
    a.key: a for a in (ManualAdapter(), AsperaAdapter())
}
