"""Claqo v3 — configurazione con AI e Web Search."""
from pydantic_settings import BaseSettings
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "Claqo"
    app_env: str = "development"
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_minutes: int = 480
    algorithm: str = "HS256"

    database_url: str = "sqlite:///./mediaflow.db"

    upload_dir: Path = Path("./uploads")
    max_upload_mb: int = 200

    host: str = "0.0.0.0"
    port: int = 8000

    # AI provider globale di fallback (usato solo se l'utente non ha configurazione propria).
    # In v3.2 la config principale è per-utente nel DB (UserAISettings).
    ai_provider: str = "disabled"

    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-6"

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:70b"

    google_api_key: Optional[str] = None
    google_model: str = "gemini-2.0-flash"

    perplexity_api_key: Optional[str] = None
    perplexity_model: str = "sonar-pro"

    # Chiave Fernet dedicata per cifrare le api_key dei provider salvate nel DB.
    # Generala con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ai_key_encryption_key: Optional[str] = None

    tavily_api_key: Optional[str] = None
    use_tavily: bool = True

    # v3.5.0-alpha.8 — Cestino: dopo quanti giorni i record nel trash vengono
    # purgati definitivamente. 0 = mai (cestino infinito, l'utente decide
    # manualmente). Default 30 giorni.
    trash_retention_days: int = 30

    # v3.5.0-alpha.66.14.2 — Auth fail-closed in produzione.
    # Se True, _resolve_current_user NON ritorna fallback "primo admin attivo"
    # quando il token è assente/invalido: ritorna None e l'endpoint deve
    # rispondere 401. Default False per continuare a supportare il flusso
    # demo single-user di sviluppo. In produzione METTERE = True.
    auth_required: bool = False

    # v3.5.0-alpha.105 — Storage S3-compatible (AWS S3 / MinIO / R2 / Wasabi).
    # Le credenziali stanno in ENV (no DB) per sicurezza. Un set di
    # credenziali serve potenzialmente più tenant/bucket.
    # Se aws_s3_endpoint è vuoto → AWS S3 standard (region inferito da bucket).
    # Per MinIO/R2 specificare endpoint completo.
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_s3_endpoint: Optional[str] = None       # es. https://s3.eu-west-1.amazonaws.com, https://abc.r2.cloudflarestorage.com
    aws_s3_region: str = "eu-west-1"
    aws_s3_use_ssl: bool = True
    # Default bucket fallback (se Tenant/Project non specifica)
    aws_s3_default_bucket: Optional[str] = None
    # Presigned URL TTL per download (secondi). Default 1h.
    aws_s3_presigned_ttl: int = 3600

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()


# v3.5.0-alpha.172.142 — Boot guard fail-closed in produzione.
# L'audit ha rilevato: secret_key default debole + auth_required=False default
# (fallback al primo utente attivo = bypass auth). Innocui in dev, voragini se
# deployati. Questo guard rifiuta l'avvio se app_env=production è insicuro.
_INSECURE_SECRET_KEYS = {"dev-secret-key-change-in-production", ""}


def assert_production_security(s: "Settings" = settings) -> None:
    """Solleva RuntimeError se app_env=production con config insicura.
    No-op in development/staging. Chiamato all'avvio (main.lifespan)."""
    if (s.app_env or "").lower() != "production":
        return
    errors = []
    if not s.auth_required:
        errors.append(
            "AUTH_REQUIRED deve essere True in produzione (ora False → "
            "fallback al primo utente attivo = bypass autenticazione)."
        )
    if (s.secret_key in _INSECURE_SECRET_KEYS) or len(s.secret_key or "") < 32:
        errors.append(
            "SECRET_KEY debole/di-default. Genera >=32 char "
            "(python -c \"import secrets;print(secrets.token_urlsafe(48))\") "
            "e impostala in .env."
        )
    if not s.ai_key_encryption_key:
        errors.append(
            "AI_KEY_ENCRYPTION_KEY mancante: le API key dei provider non "
            "sarebbero cifrate. Genera con Fernet.generate_key()."
        )
    if errors:
        raise RuntimeError(
            "Avvio bloccato — sicurezza non valida per app_env=production:\n  - "
            + "\n  - ".join(errors)
        )
