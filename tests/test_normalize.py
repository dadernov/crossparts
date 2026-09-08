import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.normalize import (
    KIND_AFTERMARKET, KIND_OEM, KIND_STANDARD,
    classify_brand, clean_number, looks_like_part_number, number_key, split_brands,
)


def test_number_key_ignores_separators_and_case():
    assert number_key("58101-H5A25") == number_key("58101 h5a25") == "58101H5A25"


def test_clean_number_collapses_whitespace():
    assert clean_number("  p 30   122 ") == "P 30 122"


def test_split_brands_only_on_padded_slash():
    assert split_brands("HYUNDAI / KIA") == ["HYUNDAI", "KIA"]
    assert split_brands("BECK/ARNLEY") == ["BECK/ARNLEY"]
    assert split_brands("GEELY, GEOMETRY") == ["GEELY", "GEOMETRY"]


def test_classify_brand():
    assert classify_brand("HYUNDAI") == KIND_OEM
    assert classify_brand("NiBK") == KIND_AFTERMARKET
    assert classify_brand("FMSI") == KIND_STANDARD


def test_looks_like_part_number_rejects_noise():
    assert looks_like_part_number("SP1424")
    assert not looks_like_part_number("")
    assert not looks_like_part_number("—")
    assert not looks_like_part_number("ABCDEF")  # no digits


def test_proxy_is_applied_only_to_listed_sources():
    """CP_PROXY_SOURCES позволяет не тратить платный прокси на доступные каталоги."""
    from app.config import Settings

    s = Settings(proxy_url="http://p:8888", proxy_sources="jnbk,mintex", api_keys="")
    assert s.proxy_for("jnbk") == "http://p:8888"
    assert s.proxy_for("mintex") == "http://p:8888"
    assert s.proxy_for("sbparts") == ""

    everywhere = Settings(proxy_url="http://p:8888", proxy_sources="", api_keys="")
    assert everywhere.proxy_for("sbparts") == "http://p:8888"

    off = Settings(proxy_url="", proxy_sources="jnbk", api_keys="")
    assert off.proxy_for("jnbk") == ""


def test_proxy_credentials_are_masked_in_messages():
    """Логин и пароль прокси не должны утекать в API и логи."""
    from app.config import Settings
    from app.sources.sbparts import SbPartsSource

    src = SbPartsSource(Settings(proxy_url="socks5://user:s3cret@1.2.3.4:1080",
                                 proxy_sources="", api_keys=""), None)
    assert src.safe_proxy() == "socks5://***@1.2.3.4:1080"
    assert "s3cret" not in src.safe_proxy()

    plain = SbPartsSource(Settings(proxy_url="socks5://1.2.3.4:1080",
                                   proxy_sources="", api_keys=""), None)
    assert plain.safe_proxy() == "socks5://1.2.3.4:1080"


def test_proxy_connection_errors_are_explained():
    import httpx

    from app.config import Settings
    from app.sources.sbparts import SbPartsSource

    src = SbPartsSource(Settings(proxy_url="socks5://user:pw@1.2.3.4:1080",
                                 proxy_sources="", api_keys=""), None)
    msg = src.describe_error(httpx.ConnectError("All connection attempts failed"))
    assert "недоступен" in msg and "туннель" in msg
    assert "pw@" not in msg

    direct = SbPartsSource(Settings(proxy_url="", api_keys=""), None)
    assert direct.describe_error(httpx.ConnectError("boom")) == "boom"
