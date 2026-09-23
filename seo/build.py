from pathlib import Path
from shutil import copy2, rmtree

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
TEMPLATES = ROOT / "templates"
SOURCE_ASSETS = ROOT.parent / "app" / "static"

env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

pages = [
    ("categories.html", "categories.html", {"page": "categories"}),
    ("brake-pads.html", "category-brake-pads.html", {"page": "categories"}),
    ("58101-h5a25.html", "number-58101-h5a25.html", {"page": "categories"}),
]

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
(PUBLIC / "sitemap.xml").write_text(
    """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://mrb-crossparts.ru/</loc></url>
  <url><loc>https://mrb-crossparts.ru/categories</loc><lastmod>2026-09-23</lastmod></url>
  <url><loc>https://mrb-crossparts.ru/categories/brake-pads</loc><lastmod>2026-09-23</lastmod></url>
  <url><loc>https://mrb-crossparts.ru/cross/58101-h5a25</loc><lastmod>2026-09-23</lastmod></url>
</urlset>
""",
    encoding="utf-8",
)

print(f"Built {len(pages)} pages in {PUBLIC}")
