import json
from pathlib import Path

from app.config import get_settings
from app.sources.nibkru import NibkRuSource


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_nibk_source_keeps_only_nibk_products_from_shared_catalogue():
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "brixo_search_58101H5A25.json").read_text()
    )
    source = NibkRuSource(get_settings(), None)
    assert source.articles(Response(payload)) == [("PN0537", "NiBK"), ("PN0537S", "NiBK")]


def test_nibk_source_describes_the_official_catalogue():
    source = NibkRuSource(get_settings(), None)
    assert source.homepage == "https://nibkbrakes.com/ru/catalog"
    assert source.key == "nibkru"
