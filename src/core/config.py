import logging
import warnings

from pydantic_settings import BaseSettings

_logger = logging.getLogger(__name__)

_DEFAULT_SECRETS = {
    "CHANGE-ME-IN-PRODUCTION",
    "CHANGE-ME-32-BYTES-KEY-HERE!!!!",
}


class Settings(BaseSettings):
    # App
    app_name: str = "AI Closer"
    debug: bool = False
    secret_key: str = "CHANGE-ME-IN-PRODUCTION"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_closer"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    refresh_token_expire_days: int = 7

    # Telegram
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_sessions_dir: str = "./sessions"

    # OpenAI
    openai_api_key: str = ""
    openai_model_main: str = "gpt-4o-mini"  # will be gpt-5-mini when available
    openai_model_fallback: str = "gpt-4o"  # will be gpt-5.1 when available
    openai_embedding_model: str = "text-embedding-3-small"
    openai_moderation_model: str = "omni-moderation-latest"

    # Instagram / Meta Graph API (official — when developer account ready)
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_webhook_verify_token: str = "easy-tour-ig-verify-2026"
    # Instagram / instagrapi (unofficial — for demo)
    instagram_username: str = ""
    instagram_password: str = ""
    instagram_session_id: str = ""
    instagram_proxy: str = ""  # e.g. http://user:pass@host:port or socks5://host:port

    # Logging
    log_format: str = "text"  # "text" for dev, "json" for production
    log_level: str = "INFO"

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003,http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002,http://127.0.0.1:3003,http://192.168.1.99:3000"

    # Encryption key for sensitive data (Telegram sessions, etc.)
    encryption_key: str = "CHANGE-ME-32-BYTES-KEY-HERE!!!!"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def check_secrets(self) -> None:
        """Warn or raise if default secrets are still in use."""
        if self.secret_key in _DEFAULT_SECRETS or self.encryption_key in _DEFAULT_SECRETS:
            msg = (
                "SECURITY: secret_key or encryption_key is set to the default value. "
                "Set SECRET_KEY and ENCRYPTION_KEY in .env before deploying to production."
            )
            if not self.debug:
                raise RuntimeError(msg)
            _logger.warning(msg)
            warnings.warn(msg, stacklevel=2)


settings = Settings()
settings.check_secrets()
