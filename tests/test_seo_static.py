import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEO = ROOT / "seo"
PUBLIC = SEO / "public"


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.canonicals = []
        self.robots = []
        self.has_title = False
        self.descriptions = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        elif tag == "title":
            self.has_title = True
        elif tag == "link" and values.get("rel") == "canonical":
            self.canonicals.append(values.get("href"))
        elif tag == "meta" and values.get("name") == "robots":
            self.robots.append(values.get("content"))
        elif tag == "meta" and values.get("name") == "description":
            self.descriptions.append(values.get("content"))


def load_content():
    return json.loads((SEO / "content.json").read_text(encoding="utf-8"))


def test_static_seo_build_is_valid_and_complete():
    result = subprocess.run(
        [sys.executable, str(SEO / "build.py")], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    assert "Built 11 pages" in result.stdout
    expected = {
        "categories.html", "brake-pads.html", "brake-discs.html", "brake-hoses.html",
        "shock-absorbers.html", "radiators.html", "58101-h5a25.html", "128424899.html",
        "1k0611701k.html", "553101g210.html", "21903130000811.html",
    }
    assert {path.name for path in PUBLIC.glob("*.html")} == expected

    for path in PUBLIC.glob("*.html"):
        parser = PageParser()
        parser.feed(path.read_text(encoding="utf-8"))
        assert parser.h1_count == 1, path.name
        assert parser.has_title, path.name
        assert len(parser.canonicals) == 1, path.name
        assert parser.canonicals[0].startswith("https://mrb-crossparts.ru/"), path.name
        assert parser.robots == ["index,follow"], path.name
        assert parser.descriptions and parser.descriptions[0], path.name


def test_sitemap_contains_only_published_canonical_pages():
    content = load_content()
    expected = {
        "https://mrb-crossparts.ru/",
        "https://mrb-crossparts.ru/categories",
        *{f"https://mrb-crossparts.ru/categories/{item['slug']}" for item in content["categories"]},
        *{f"https://mrb-crossparts.ru/cross/{item['slug']}" for item in content["snapshots"]},
    }
    tree = ET.parse(PUBLIC / "sitemap.xml")
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    actual = {node.text for node in tree.findall("sm:url/sm:loc", namespace)}
    assert actual == expected


def test_published_rows_exist_in_reviewed_catalogue_audit():
    content = load_content()
    audit = json.loads(
        (ROOT / "docs/audits/2026-09-22/sources-final.json").read_text(encoding="utf-8")
    )
    source_keys = {
        "ATE": "ate", "Brembo": "brembo", "Brixo / NiBK": "nibkru",
        "SB Parts": "sbparts", "TRIALLI": "trialli", "ZIMMERMANN": "zimmermann",
        "MONAER": "monaer", "LYNXauto": "lynxauto", "FEBEST": "febest",
        "METACO": "metaco", "TORR": "torr", "GANZ": "ganz",
    }
    audited = {
        (item["group"], item["oe"], item["source"]): set(item["products"])
        for item in audit if item["status"] == "ok"
    }
    for snapshot in content["snapshots"]:
        for row in snapshot["rows"]:
            key = (snapshot["group"], snapshot["input_number"], source_keys[row["source"]])
            assert row["number"] in audited[key], (snapshot["id"], row)


def test_each_category_has_a_reviewed_number_page():
    content = load_content()
    groups = {item["group"] for item in content["snapshots"]}
    assert groups == {item["key"] for item in content["categories"]}
