from __future__ import annotations

import json
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
    # Optional bootstrap accounts: "login:password,login2:password2".
    users: str = ""
    session_secret: str = "change-this-crossparts-session-secret"
    # Лимит именно поисковых позиций (один OE-номер = одна позиция), на аккаунт.
    requests_per_account: int = 1000
    # Passwordless demo accounts created from the start page.
    trial_requests: int = 10
    source_timeout: int = 45
    job_concurrency: int = 4
    # Large uploads are exposed as sequential downloadable jobs. The final
    # combined job is added to history after all chunks finish.
    job_chunk_sizes: str = "gerat:50,admin:10"
    paced_tenants: str = "gerat"
    paced_daily_fast_limit: int = Field(default=330, ge=1, le=100000)
    paced_fast_window_seconds: int = Field(default=14400, ge=1, le=86400)
    paced_slow_interval_seconds: int = Field(default=1200, ge=1, le=86400)
    source_concurrency: int = 2
    # Pause a failing upstream after one blocked/error response so every new
    # number does not wait for the same timeout again.
    source_failure_cooldown_seconds: int = Field(default=300, ge=0, le=3600)
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
    # download page.  An empty path prevents the W1 candidate from querying an index.
    metaco_index_path: str = ""
    # Immutable index built from a reviewed public MARSHALL XLSX catalogue.
    # Empty means that the W1 candidate cannot answer customer requests.
    marshall_index_path: str = ""
    # Immutable index built from reviewed public MONAER product cards.
    monaer_index_path: str = ""
    # JSON map for candidate adapters, for example:
    # {"metaco":{"groups":["brake_pads"],"tenants":["pilot"],"default":true}}
    # A candidate enabled for a tenant also participates in searches without a
    # selected group.  Set ``ungrouped: false`` only for a source that cannot
    # safely answer an unclassified number.
    pilot_rules: str = ""

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

    @property
    def job_chunk_size_map(self) -> dict[str, int]:
        out = {}
        for chunk in self.job_chunk_sizes.split(","):
            tenant, sep, raw_size = chunk.strip().partition(":")
            if not tenant or not sep:
                continue
            try:
                size = int(raw_size)
            except ValueError:
                continue
            if size > 0:
                out[tenant.strip().lower()] = size
        return out

    def job_chunk_size_for(self, tenant: str) -> int:
        return self.job_chunk_size_map.get(tenant.lower(), 0)

    @property
    def paced_tenant_keys(self) -> set[str]:
        return {value.strip().lower() for value in self.paced_tenants.split(",") if value.strip()}

    def pace_enabled_for(self, tenant: str) -> bool:
        return tenant.lower() in self.paced_tenant_keys

    @property
    def pilot_rule_map(self) -> dict[str, dict]:
        if not self.pilot_rules.strip():
            return {}
        try:
            raw = json.loads(self.pilot_rules)
        except (TypeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out = {}
        for source, rule in raw.items():
            if not isinstance(source, str) or not isinstance(rule, dict):
                continue
            groups = rule.get("groups")
            tenants = rule.get("tenants")
            if not isinstance(groups, list) or not isinstance(tenants, list):
                continue
            groups = [value for value in groups if isinstance(value, str) and value]
            tenants = [value for value in tenants if isinstance(value, str) and value]
            if not groups or not tenants:
                continue
            out[source] = {
                "groups": groups,
                "tenants": tenants,
                "default": rule.get("default") is True,
                "ungrouped": rule.get("ungrouped") is not False,
            }
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
