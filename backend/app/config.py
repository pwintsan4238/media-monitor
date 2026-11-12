import pathlib

from pydantic_settings import BaseSettings, SettingsConfigDict

_URI_FILE = pathlib.Path(__file__).resolve().parent.parent / ".dev_db_uri"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = ""
    admin_username: str = "admin"
    admin_password_hash: str = ""
    jwt_secret: str = "dev-insecure-change-me"
    jwt_expire_hours: int = 12
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    crawler_user_agent: str = "MediaMonitorBot/0.1"
    cors_origins: str = "http://localhost:3000"

    def resolved_db_url(self) -> str:
        url = self.database_url
        if not url and _URI_FILE.exists():
            url = _URI_FILE.read_text().strip()
        if not url:
            raise RuntimeError("No DATABASE_URL set and dev DB not running (python dev_db.py)")
        for pre in ("postgresql://", "postgres://"):
            if url.startswith(pre):
                url = "postgresql+psycopg://" + url[len(pre):]
        return url


settings = Settings()
