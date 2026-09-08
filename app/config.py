from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable through env vars or a .env file."""

    model_config = SettingsConfigDict(env_prefix="CP_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./data/crossparts.db"

    # "key:tenant,key2:tenant2". Empty string disables authentication (dev mode).
    api_keys: str = "demo-key:Demo"

    source_timeout: int = 45
    job_concurrency: int = 4
    source_concurrency: int = 2
    cache_ttl_hours: int = 168
    max_products_per_oe: int = 5
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    proxy_url: str = ""
    # Ключи источников, которые должны ходить через CP_PROXY_URL.
    # Пусто => прокси применяется ко всем источникам.
    proxy_sources: str = ""
    # Пройти Cloudflare-challenge реальным браузером и переиспользовать его cookies.
    # Требует установленного Chromium (python3 -m playwright install chromium).
    browser_fallback: bool = True
    # Sources active by default when a request does not name any explicitly.
    enabled_sources: str = "sbparts,brembo"

    @property
    def api_key_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for chunk in self.api_keys.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            key, _, tenant = chunk.partition(":")
            out[key.strip()] = tenant.strip() or "default"
        return out

    @property
    def proxy_source_keys(self) -> set[str]:
        return {s.strip() for s in self.proxy_sources.split(",") if s.strip()}

    def proxy_for(self, source_key: str) -> str:
        """Прокси для конкретного источника ("" — идти напрямую).

        Прокси обычно платный и метрический, поэтому через него имеет смысл
        пускать только те каталоги, которые иначе недоступны.
        """
        if not self.proxy_url:
            return ""
        keys = self.proxy_source_keys
        if keys and source_key not in keys:
            return ""
        return self.proxy_url

    @property
    def default_sources(self) -> list[str]:
        return [s.strip() for s in self.enabled_sources.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
