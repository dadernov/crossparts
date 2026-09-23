import json
import re
from datetime import date
from pathlib import Path
from shutil import copy2, rmtree
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
TEMPLATES = ROOT / "templates"
SOURCE_ASSETS = ROOT.parent / "app" / "static"
CONTENT = ROOT / "content.json"
ORIGIN = "https://mrb-crossparts.ru"
BUILD_DATE = date(2026, 9, 23)

CATEGORY_FIELDS = {
    "key", "slug", "name", "eyebrow", "description", "lead", "image",
    "image_alt", "example", "example_slug", "specifics", "workflow", "batch", "sources",
}
SNAPSHOT_FIELDS = {
    "id", "slug", "group", "input_brand", "input_number", "checked_at",
    "checked_at_display", "review", "rows",
}
PRIVATE_FIELDS = {
    "tenant", "username", "password", "password_hash", "ip", "guest_identifier",
    "uploaded_filename", "customer_sku", "credentials", "proxy_url", "internal_errors",
}


def _require_http_url(value: str, label: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise ValueError(f"{label}: expected a public HTTP(S) URL")


def _assert_no_private_fields(value, path: str = "content") -> None:
    if isinstance(value, dict):
        forbidden = PRIVATE_FIELDS.intersection(value)
        if forbidden:
            raise ValueError(f"{path}: private fields are forbidden: {sorted(forbidden)}")
        for key, item in value.items():
            _assert_no_private_fields(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_private_fields(item, f"{path}[{index}]")


def load_content() -> tuple[dict, list[dict], list[dict]]:
    payload = json.loads(CONTENT.read_text(encoding="utf-8"))
    if set(payload) != {"schema_version", "reviewed_at", "categories", "snapshots"}:
        raise ValueError("content.json: unknown or missing top-level fields")
    if payload["schema_version"] != "1.0":
        raise ValueError("content.json: unsupported schema version")
    _assert_no_private_fields(payload)

    categories = payload["categories"]
    snapshots = payload["snapshots"]
    if len(categories) != 5:
        raise ValueError("SEO pilot must contain exactly five categories")
    by_key: dict[str, dict] = {}
    category_slugs: set[str] = set()
    for category in categories:
        if set(category) != CATEGORY_FIELDS:
            raise ValueError(f"category {category.get('key')}: unknown or missing fields")
        if category["key"] in by_key or category["slug"] in category_slugs:
            raise ValueError("category keys and slugs must be unique")
        if not category["sources"]:
            raise ValueError(f"category {category['key']}: sources are required")
        for source in category["sources"]:
            if set(source) != {"name", "url"}:
                raise ValueError(f"category {category['key']}: invalid source fields")
            _require_http_url(source["url"], f"category {category['key']} source")
        by_key[category["key"]] = category
        category_slugs.add(category["slug"])

    snapshot_slugs: set[str] = set()
    for snapshot in snapshots:
        if set(snapshot) != SNAPSHOT_FIELDS:
            raise ValueError(f"snapshot {snapshot.get('id')}: unknown or missing fields")
        if snapshot["slug"] in snapshot_slugs or snapshot["group"] not in by_key:
            raise ValueError(f"snapshot {snapshot['id']}: duplicate slug or unknown group")
        snapshot_slugs.add(snapshot["slug"])
        review = snapshot["review"]
        if set(review) != {"status", "reviewed_at", "identity_confirmed"}:
            raise ValueError(f"snapshot {snapshot['id']}: invalid review fields")
        if review["status"] != "reviewed" or review["identity_confirmed"] is not True:
            raise ValueError(f"snapshot {snapshot['id']}: publication requires completed review")
        checked_at = date.fromisoformat(snapshot["checked_at"])
        if checked_at > BUILD_DATE or (BUILD_DATE - checked_at).days > 30:
            raise ValueError(f"snapshot {snapshot['id']}: evidence is future-dated or stale")
        if not re.fullmatch(r"[a-z0-9-]+", snapshot["slug"]):
            raise ValueError(f"snapshot {snapshot['id']}: unsafe slug")
        if not snapshot["rows"]:
            raise ValueError(f"snapshot {snapshot['id']}: verified rows are required")
        seen_rows: set[tuple[str, str]] = set()
        for row in snapshot["rows"]:
            if set(row) != {"brand", "number", "source", "source_url"}:
                raise ValueError(f"snapshot {snapshot['id']}: invalid row fields")
            _require_http_url(row["source_url"], f"snapshot {snapshot['id']} source")
            key = (re.sub(r"\W", "", row["brand"].casefold()), re.sub(r"\W", "", row["number"].casefold()))
            if key in seen_rows:
                raise ValueError(f"snapshot {snapshot['id']}: duplicate brand/number row")
            seen_rows.add(key)
        category = by_key[snapshot["group"]]
        if category["example_slug"] == snapshot["slug"] and category["example"] != snapshot["input_number"]:
            raise ValueError(f"snapshot {snapshot['id']}: category example does not match")
    if len(snapshots) < 5 or len(snapshots) > 10:
        raise ValueError("SEO pilot requires from five to ten reviewed number pages")
    return payload, categories, snapshots

env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

payload, categories, snapshots = load_content()
by_key = {category["key"]: category for category in categories}
pages = [("categories.html", "categories.html", {"page": "categories", "categories": categories})]
for category in categories:
    related = [item for item in categories if item["key"] != category["key"]]
    structured_data = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": f"Кросс-номера: {category['name'].lower()}",
        "url": f"{ORIGIN}/categories/{category['slug']}",
        "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Категории", "item": f"{ORIGIN}/categories"},
            {"@type": "ListItem", "position": 2, "name": category["name"]},
        ]},
    }
    pages.append((f"{category['slug']}.html", "category.html", {
        "page": "categories", "category": category, "related_categories": related,
        "structured_data": structured_data,
    }))
for snapshot in snapshots:
    category = by_key[snapshot["group"]]
    structured_data = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": f"Кроссы и аналоги {snapshot['input_number']}",
        "url": f"{ORIGIN}/cross/{snapshot['slug']}",
        "dateModified": snapshot["review"]["reviewed_at"],
        "about": {"@type": "Thing", "name": f"OE / OEM {snapshot['input_number']}"},
    }
    count = len(snapshot["rows"])
    row_word = "соответствие" if count % 10 == 1 and count % 100 != 11 else (
        "соответствия" if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}
        else "соответствий"
    )
    pages.append((f"{snapshot['slug']}.html", "number.html", {
        "page": "categories", "category": category, "snapshot": snapshot,
        "structured_data": structured_data, "row_word": row_word,
    }))

if PUBLIC.exists():
    rmtree(PUBLIC)
PUBLIC.mkdir(parents=True, exist_ok=True)
(PUBLIC / "assets" / "categories").mkdir(parents=True, exist_ok=True)
(PUBLIC / "assets" / "fonts").mkdir(parents=True, exist_ok=True)

for output, template, context in pages:
    rendered = env.get_template(template).render(**context)
    (PUBLIC / output).write_text(rendered, encoding="utf-8")

copy2(ROOT / "static" / "seo.css", PUBLIC / "assets" / "seo.css")
copy2(ROOT / "static" / "seo.js", PUBLIC / "assets" / "seo.js")
copy2(SOURCE_ASSETS / "fonts" / "Onest.ttf", PUBLIC / "assets" / "fonts" / "Onest.ttf")
copy2(SOURCE_ASSETS / "favicon.svg", PUBLIC / "assets" / "favicon.svg")
copy2(SOURCE_ASSETS / "images" / "welcome-automotive-expressive.png", PUBLIC / "assets" / "background-main.png")
for name in ("pads.jpg", "discs.png", "hoses.png", "shocks.png", "radiators.png"):
    copy2(SOURCE_ASSETS / "images" / "categories" / name, PUBLIC / "assets" / "categories" / name)

(PUBLIC / "robots.txt").write_text(
    "User-agent: *\nAllow: /\nSitemap: https://mrb-crossparts.ru/sitemap.xml\n",
    encoding="utf-8",
)
sitemap_urls = [f"  <url><loc>{ORIGIN}/</loc></url>",
                f"  <url><loc>{ORIGIN}/categories</loc><lastmod>{payload['reviewed_at']}</lastmod></url>"]
sitemap_urls.extend(
    f"  <url><loc>{ORIGIN}/categories/{category['slug']}</loc><lastmod>{payload['reviewed_at']}</lastmod></url>"
    for category in categories
)
sitemap_urls.extend(
    f"  <url><loc>{ORIGIN}/cross/{snapshot['slug']}</loc><lastmod>{snapshot['review']['reviewed_at']}</lastmod></url>"
    for snapshot in snapshots
)
(PUBLIC / "sitemap.xml").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + "\n".join(sitemap_urls) + "\n</urlset>\n",
    encoding="utf-8",
)

print(f"Built {len(pages)} pages in {PUBLIC}")
