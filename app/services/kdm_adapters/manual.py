from app.services.kdm_adapters.base import KdmAdapter


class ManualAdapter(KdmAdapter):
    name = "manual"

    def send_kdm(self, req) -> dict:
        # v1: nessun invio automatico; l'operatore consegna a mano.
        return {"ok": True, "mode": "manual"}
