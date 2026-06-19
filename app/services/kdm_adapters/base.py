"""Base adapter consegna KDM. Fase 2: qube_wire / gofilex con chiave Fernet."""


class KdmAdapter:
    name = "base"

    def send_kdm(self, req) -> dict:
        raise NotImplementedError

    def fetch_certs(self, facility) -> list:
        return []
