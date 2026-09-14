"""Official NiBK catalogue facade — https://nibkbrakes.com/ru/catalog.

The current public NiBK catalogue is backed by Brixo catalogue data. Its direct
``core.brixogroup.com/api/v1`` endpoint currently returns a server error to
non-browser clients; the matching public Brixo JSON endpoint exposes the same
product cards and references. This adapter uses that shared public data path;
it does not imitate a browser or bypass a challenge.
"""
from __future__ import annotations

from ..groups import BRAKE_DISCS, BRAKE_PADS
from .brixo import BrixoSource


class NibkRuSource(BrixoSource):
    """NiBK-only view of the shared public catalogue API."""

    key = "nibkru"
    title = "NiBK (nibkbrakes.com)"
    homepage = "https://nibkbrakes.com/ru/catalog"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS)
    brand_filter = "NIBK"
    note = (
        "Официальный каталог NiBK. Один поиск и максимум пять карточек на номер; "
        "дальше используется кэш."
    )
