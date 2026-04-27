"""MediaFlow v3 — configurazione con AI e Web Search."""
from pydantic_settings import BaseSettings
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "MediaFlow"
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
