"""Normalisation of part numbers and brand names.

Catalogues write the same OE number in many shapes: ``58101-H5A25``,
``58101 H5A25``, ``58101H5A25``.  Everything is compared on a *key* built by
dropping non-alphanumerics and upper-casing, while the human-readable form is
kept for the output file.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9A-Z]+")
_WS = re.compile(r"\s+")
# Only split on a slash that is padded with spaces: "HYUNDAI / KIA" is two
# brands, "BECK/ARNLEY" is one.
_BRAND_SPLIT = re.compile(r"\s+/\s+|\s*,\s*")

#: Brands that publish their own aftermarket catalogue numbers.
AFTERMARKET_BRANDS = {
    "AKEBONO", "ASHIKA", "ATE", "AVA", "BENDIX", "BENDIX AUS", "BILSTEIN",
    "BLUE PRINT", "BOGE", "BOSCH", "BRANNOR", "BRECK", "BREMBO", "BREMSI",
    "CTR", "DELPHI", "DENCKERMANN", "DYNAMATRIX", "EBC", "FAP", "FEBI",
    "FENOX", "FERODO", "FINWHALE", "FREMAX", "FRICTION MASTER", "GERAT",
    "HEL", "HELLA", "HI-Q", "HOLA", "ICER", "JAPANPARTS", "JAPKO", "JURID",
    "KASHIYAMA", "KAVO PARTS", "KONI", "KYB", "LPR", "LUZAR", "LYNXAUTO",
    "MANDO", "MAPCO", "MARSHALL", "MASUMA", "METELLI", "MEYLE", "MINTEX",
    "MIRAGLIO", "MONAER", "NIBK", "NIPPARTS", "NISSENS", "NISSHINBO", "NK",
    "NRF", "OPTIMAL", "PAGID", "PATRON", "PILENGA", "QUICK BRAKE", "REMSA",
    "ROADHOUSE", "SACHS", "SAKURA", "SALURA", "SANGSIN", "SB NAGAMOCHI", "SBS",
    "SPEEDMATE", "STELLOX", "SWAG", "TEXTAR", "TOKICO", "TRIALLI", "TRW",
    "VALEO", "ZIMMERMANN",
}

#: Industry standards rather than a manufacturer.
STANDARD_BRANDS = {"FMSI", "WVA", "ECE", "SAE", "GG", "D"}

# Vehicle manufacturers can also appear in a supplier's "replacement" file.
# Their numbers remain OEM references regardless of the input filename.
OEM_BRANDS = {
    "ACURA", "ALFA ROMEO", "AUDI", "BAIC", "BMW", "BUICK", "BYD",
    "CADILLAC", "CHANGAN", "CHERY", "CHEVROLET", "CHRYSLER", "CITROEN",
    "CITROEN-PEUGEOT", "DACIA", "DAEWOO", "DAIHATSU", "DATSUN", "DODGE",
    "FAW", "FIAT", "FORD", "GAZ", "GEELY", "GENESIS", "GM", "GREAT WALL",
    "HAVAL", "HONDA", "HYUNDAI", "HYUNDAI-KIA", "INFINITI", "ISUZU",
    "IVECO", "JAC", "JAGUAR", "JEEP", "KIA", "LADA", "LAND ROVER",
    "LEXUS", "LIFAN", "LINCOLN", "MAN", "MAZDA", "MERCEDES BENZ",
    "MERCEDES-BENZ", "MINI", "MITSUBISHI", "MOSKVICH", "NISSAN", "OPEL",
    "PEUGEOT", "PORSCHE", "RENAULT", "ROVER", "SAAB", "SAIC", "SCANIA",
    "SEAT", "SKODA", "SMART", "SSANGYONG", "SUBARU", "SUZUKI", "TOYOTA",
    "UAZ", "VAG", "VAZ", "VOLKSWAGEN", "VOLVO", "VW", "ZAZ", "ZIL",
}

KIND_OEM = "oem"
KIND_AFTERMARKET = "aftermarket"
KIND_STANDARD = "standard"


def number_key(value: str) -> str:
    """Canonical comparison key for a part number."""
    return _NON_ALNUM.sub("", (value or "").upper())


def clean_number(value: str) -> str:
    """Human-readable part number: trimmed, single-spaced, upper-cased."""
    return _WS.sub(" ", (value or "").replace("\xa0", " ").strip()).upper()


def clean_brand(value: str) -> str:
    return _WS.sub(" ", (value or "").replace("\xa0", " ").strip()).upper()


def split_brands(value: str) -> list[str]:
    """``"HYUNDAI / KIA"`` -> ``["HYUNDAI", "KIA"]``."""
    parts = [clean_brand(p) for p in _BRAND_SPLIT.split(value or "")]
    return [p for p in parts if p] or [clean_brand(value)]


def classify_brand(brand: str) -> str:
    b = clean_brand(brand)
    if b in STANDARD_BRANDS:
        return KIND_STANDARD
    if b in AFTERMARKET_BRANDS:
        return KIND_AFTERMARKET
    return KIND_OEM


def classify_reference_brand(brand: str, fallback: str) -> str:
    """Classify known brands while preserving unknown file semantics."""
    canonical = clean_brand(brand)
    if canonical in STANDARD_BRANDS:
        return KIND_STANDARD
    if canonical in OEM_BRANDS:
        return KIND_OEM
    if canonical in AFTERMARKET_BRANDS:
        return KIND_AFTERMARKET
    return fallback


def looks_like_part_number(value: str) -> bool:
    """Reject obvious noise (empty cells, prose, pure punctuation)."""
    key = number_key(value)
    if len(key) < 3 or len(key) > 40:
        return False
    if not any(ch.isdigit() for ch in key):
        return False
    return True
