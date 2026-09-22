from __future__ import annotations

import time
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..normalize import (
    classify_brand,
    clean_brand,
    clean_number,
    looks_like_part_number,
    number_key,
    split_brands,
)


class SourceStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class Cross:
    """One cross-reference row: a brand plus its part number."""

    brand: str
    number: str
    kind: str
    source: str
    source_product: str | None = None
    url: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.brand, number_key(self.number))


@dataclass
class SourceResult:
    source: str
    status: SourceStatus
    crosses: list[Cross] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    message: str | None = None
    elapsed_ms: int = 0
    url: str | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "status": self.status.value,
            "message": self.message,
            "elapsed_ms": self.elapsed_ms,
            "url": self.url,
            "products": self.products,
            "crosses": [
                {
                    "brand": c.brand,
                    "number": c.number,
                    "kind": c.kind,
                    "source": c.source,
                    "source_product": c.source_product,
                    "url": c.url,
                }
                for c in self.crosses
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceResult":
        return cls(
            source=data["source"],
            status=SourceStatus(data["status"]),
            crosses=[Cross(**c) for c in data.get("crosses", [])],
            products=data.get("products", []),
            message=data.get("message"),
            elapsed_ms=data.get("elapsed_ms", 0),
            url=data.get("url"),
        )


class BaseSource:
    """A catalogue that can answer 'which numbers cross to this OE number?'."""

    key: str = ""
    title: str = ""
    homepage: str = ""
    #: ``True`` once the parser has been checked against the live site.
    verified: bool = False
    #: Товарные группы, которые покрывает источник (ключи из app.groups).
    groups: tuple[str, ...] = ()
    #: Human note shown in ``GET /api/v1/sources``.
    note: str = ""

    def __init__(self, settings, http_factory, pool=None):
        self.settings = settings
        self._http_factory = http_factory
        self.pool = pool

    async def lookup(self, oe: str) -> SourceResult:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def cache_version(self) -> str:
        """Version component for cache keys backed by immutable snapshots."""
        return ""

    # -- helpers shared by adapters -------------------------------------

    def make_cross(
        self,
        brand: str,
        number: str,
        *,
        product: str | None = None,
        url: str | None = None,
        kind: str | None = None,
    ) -> list[Cross]:
        """Turn one raw (brand, number) pair into normalised ``Cross`` rows.

        A cell such as ``"HYUNDAI / KIA"`` yields one row per brand.
        """
        num = clean_number(number)
        if not looks_like_part_number(num):
            return []
        out = []
        for b in split_brands(brand):
            b = clean_brand(b)
            if not b:
                continue
            out.append(
                Cross(
                    brand=b,
                    number=num,
                    kind=kind or classify_brand(b),
                    source=self.key,
                    source_product=product,
                    url=url,
                )
            )
        return out

    def safe_proxy(self) -> str:
        """Прокси без логина и пароля — такое не стыдно положить в лог и в API."""
        proxy = self.proxy
        if not proxy or "@" not in proxy:
            return proxy
        scheme, _, rest = proxy.partition("://")
        return f"{scheme}://***@{rest.rpartition('@')[2]}"

    def describe_error(self, exc: Exception) -> str:
        """Сетевую ошибку через прокси надо называть своим именем.

        Иначе «All connection attempts failed» одинаково выглядит и при упавшем
        туннеле, и при недоступном сайте, а чинить это разные вещи.
        """
        text = str(exc)[:200] or exc.__class__.__name__
        if not self.proxy:
            return text
        name = exc.__class__.__name__
        if name in ("ConnectError", "ProxyError", "ConnectTimeout", "NetworkError"):
            return (f"прокси {self.safe_proxy()} недоступен ({text}). "
                    f"Проверьте, что туннель поднят.")
        return text

    @property
    def proxy(self) -> str:
        """Прокси, назначенный этому источнику (см. CP_PROXY_SOURCES)."""
        return self.settings.proxy_for(self.key)

    async def browser_cookies(self, url: str, *, cleared) -> tuple[list[dict], str] | None:
        """Открыть страницу настоящим браузером и забрать cookies.

        Нужно для сайтов за Cloudflare: challenge решается один раз в браузере,
        а дальше дешёвые httpx-запросы идут с полученным ``cf_clearance``.
        ``cleared(title, html)`` говорит, что защита пройдена.
        """
        if self.pool is None or not self.settings.browser_fallback:
            return None
        context = await self.pool.new_context(proxy_url=self.proxy)
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded",
                            timeout=self.settings.source_timeout * 1000)
            # На нормальном IP Cloudflare отпускает за 2-5 секунд; больше ждать
            # смысла нет — значит адрес не проходит в принципе.
            html = ""
            for _ in range(6):
                html = await page.content()
                if cleared(await page.title(), html):
                    break
                await page.wait_for_timeout(2000)
            return await context.cookies(), html
        except Exception:
            return None
        finally:
            await context.close()

    @staticmethod
    def timer() -> float:
        return time.monotonic()

    @staticmethod
    def elapsed(started: float) -> int:
        return int((time.monotonic() - started) * 1000)


def file_snapshot_version(path: str | Path | None) -> str:
    """Return a stable short hash for a configured immutable catalogue file."""
    if not path:
        return ""
    snapshot = Path(path)
    if not snapshot.is_file():
        return "missing"
    digest = hashlib.sha256()
    with snapshot.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]
