from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable through env vars or a .env file."""

    model_config = SettingsConfigDict(env_prefix="CP_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./data/crossparts.db"

    # "key:tenant,key2:tenant2". Empty string disables authentication (dev mode).
    api_keys: str = "demo-key:Demo"
    # Клиентские учётные записи для MVP: "login:password,login2:password2".
    # Учётные записи выдаются администратором. Тестовая: 0 / 0.
    users: str = "0:0"
    session_secret: str = "change-this-crossparts-session-secret"
    # Лимит именно поисковых позиций (один OE-номер = одна позиция), на аккаунт.
    requests_per_account: int = 1000
    # Passwordless demo accounts created from the start page.
    trial_requests: int = 10
    source_timeout: int = 45
    job_concurrency: int = 4
    source_concurrency: int = 2
    cache_ttl_hours: int = 168
    max_products_per_oe: int = 5
    # Hidden, opt-in second pass through catalogues that returned not_found.
    circular_search_enabled: bool = False
    circular_search_max_queries: int = Field(default=6, ge=0, le=100)
    circular_search_max_queries_per_source: int = Field(default=2, ge=0, le=20)
    circular_search_timeout: float = Field(default=20, gt=0, le=300)
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
    enabled_sources: str = (
        "sbparts,brembo,trialli,nibkru,brixo,luzar,nissens,kyb,hola,brannor,hel"
    )
    # Immutable index built from reviewed snapshots on the official METACO
    # download page.  An empty path keeps the unregistered W1 adapter inert.
    metaco_index_path: str = ""

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
    def user_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for chunk in self.users.split(","):
            login, sep, password = chunk.strip().partition(":")
            if login and sep and password:
                out[login.strip().lower()] = password
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
