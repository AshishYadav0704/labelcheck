"""Application settings, read once from environment variables.

Every setting has a safe default so the app starts locally with no config;
production values are set as environment variables on the host.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # AI provider for label photos + plain-language explanations.
    # AI_PROVIDER = auto | anthropic | gemini | none. "auto" picks whichever key is set
    # (Anthropic first). With none, photos are read by OCR and summaries use templates.
    ai_provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "auto").strip().lower())
    ai_timeout_s: int = field(default_factory=lambda: _int("AI_TIMEOUT_S", 60))

    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"))
    anthropic_base_url: str = field(default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"))

    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))
    gemini_base_url: str = field(
        default_factory=lambda: os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    )

    # Offline OCR fallback (Tesseract) for label photos when no AI provider is available.
    ocr_enabled: bool = field(default_factory=lambda: _bool("OCR_ENABLED", True))
    ocr_languages: str = field(default_factory=lambda: os.getenv("OCR_LANGUAGES", "eng"))

    # Open Food Facts (barcode lookup + alternatives)
    off_base_url: str = field(default_factory=lambda: os.getenv("OFF_BASE_URL", "https://world.openfoodfacts.org"))
    off_user_agent: str = field(
        default_factory=lambda: os.getenv("OFF_USER_AGENT", "LabelCheck/1.0 (set OFF_USER_AGENT to include a contact email)")
    )
    off_timeout_s: int = field(default_factory=lambda: _int("OFF_TIMEOUT_S", 10))

    # Storage
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(BACKEND_DIR / "data_store"))))
    web_dir: Path = field(default_factory=lambda: Path(os.getenv("WEB_DIR", str(REPO_DIR / "web"))))

    # Limits
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 10))
    max_images: int = field(default_factory=lambda: _int("MAX_IMAGES", 4))
    rate_ai_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_AI_PER_MIN", 8))
    rate_ai_per_day: int = field(default_factory=lambda: _int("RATE_LIMIT_AI_PER_DAY", 60))
    rate_video_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_VIDEO_PER_MIN", 6))
    rate_default_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_DEFAULT_PER_MIN", 120))
    # Only enable behind a reverse proxy that sets X-Forwarded-For itself (the bundled
    # Caddy config does); otherwise clients could spoof their IP to dodge rate limits.
    trust_proxy_headers: bool = field(default_factory=lambda: _bool("TRUST_PROXY_HEADERS", False))

    # HTTP
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS"))

    @property
    def db_path(self) -> Path:
        return Path(os.getenv("DB_PATH", str(self.data_dir / "labelcheck.db")))

    @property
    def video_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def resolved_ai_provider(self) -> str:
        if self.ai_provider in ("anthropic", "claude"):
            return "anthropic" if self.anthropic_api_key else "none"
        if self.ai_provider == "gemini":
            return "gemini" if self.gemini_api_key else "none"
        if self.ai_provider == "none":
            return "none"
        if self.anthropic_api_key:
            return "anthropic"
        if self.gemini_api_key:
            return "gemini"
        return "none"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")


@lru_cache
def get_settings() -> Settings:
    return Settings()
