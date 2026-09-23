"""Normalization and persistence for direct product-to-vehicle applicability."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

from sqlalchemy import select

from .models import FitmentEvidence, FitmentPart, FitmentRecord, utcnow
from .normalize import number_key


MAKE_ALIASES = {
    "VW": "VOLKSWAGEN", "VOLKSWAGEN (VW)": "VOLKSWAGEN",
    "MERCEDES-BENZ": "MERCEDES BENZ", "MERCEDES BENZ": "MERCEDES BENZ",
    "KIA (DYK)": "KIA", "FIAT / ALFA ROMEO / LANCIA": "FIAT / ALFA ROMEO / LANCIA",
}

SEMANTIC_FIELDS = (
    "make_normalized", "model_normalized", "generation", "year_from", "year_to",
    "month_from", "month_to", "end_is_open", "engine_code", "engine_cc",
    "power_kw", "power_hp", "body", "transmission", "axle", "restrictions",
)


def normalize_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_make(value: object) -> str:
    raw = normalize_name(value).upper()
    return MAKE_ALIASES.get(raw, raw)


def normalize_model(value: object) -> str:
    return normalize_name(value).upper()


def normalize_result(result: dict, source) -> dict:
    """Fill the common contract without inventing source data."""
    normalized = dict(result)
    parser_version = source.cache_key.rsplit(":v", 1)[-1]
    applications, seen = [], set()
    for raw in result.get("applications") or []:
        item = dict(raw)
        for key in ("make", "model", "modification", "engine_code", "engine_cc",
                    "power_kw", "power_hp", "raw_period", "info", "raw_vehicle_label"):
            item[key] = normalize_name(item.get(key))
        for key in ("generation", "body", "transmission", "axle"):
            item[key] = normalize_name(item.get(key)) or None
        item["restrictions"] = sorted({normalize_name(value) for value in item.get("restrictions") or [] if normalize_name(value)})
        item["make_normalized"] = normalize_make(item["make"])
        item["model_normalized"] = normalize_model(item["model"])
        item["verification_status"] = item.get("verification_status") or "confirmed"
        item["raw_vehicle_label"] = item["raw_vehicle_label"] or " ".join(filter(None, [item["make"], item["model"], item["modification"]]))
        for key in ("year_from", "year_to", "month_from", "month_to"):
            item.setdefault(key, None)
        item["end_is_open"] = bool(item.get("end_is_open"))
        item["evidence"] = {
            "source_key": source.key, "source_product_id": normalized.get("number") or "",
            "source_url": normalized.get("source_url") or "", "fetched_at": normalized.get("checked_at"),
            "parser_version": parser_version, "raw_vehicle_label": item["raw_vehicle_label"],
            "raw_period": item["raw_period"], "match_basis": "direct_product",
        }
        identity = tuple(json.dumps(item.get(key), ensure_ascii=False, sort_keys=True) for key in SEMANTIC_FIELDS)
        if identity not in seen:
            seen.add(identity); applications.append(item)
    normalized["applications"] = applications
    normalized["parser_version"] = parser_version
    normalized["response_status"] = {
        "ok": "found", "not_found": "not_found", "blocked": "source_error", "error": "source_error",
    }.get(normalized.get("status"), "source_error")
    return normalized


def identity_hash(application: dict) -> str:
    payload = {key: application.get(key) for key in SEMANTIC_FIELDS}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


async def persist_result(session_factory, result: dict) -> None:
    if result.get("status") != "ok":
        return
    brand = normalize_name(result.get("brand")).upper()
    article = number_key(result.get("number") or "")
    group = normalize_name(result.get("group"))
    if not brand or not article or not group:
        return
    async with session_factory() as session:
        part = (
            await session.execute(select(FitmentPart).where(
                FitmentPart.brand_normalized == brand,
                FitmentPart.part_number_normalized == article,
                FitmentPart.product_group == group,
            ))
        ).scalar_one_or_none()
        if part is None:
            part = FitmentPart(brand_normalized=brand, part_number_normalized=article,
                               product_group=group)
            session.add(part); await session.flush()
        for application in result.get("applications") or []:
            digest = identity_hash(application)
            record = (
                await session.execute(select(FitmentRecord).where(
                    FitmentRecord.part_id == part.id,
                    FitmentRecord.identity_hash == digest,
                ))
            ).scalar_one_or_none()
            if record is None:
                record = FitmentRecord(
                    part_id=part.id, identity_hash=digest,
                    make_normalized=application.get("make_normalized") or "",
                    model_normalized=application.get("model_normalized") or "",
                    year_from=application.get("year_from"), year_to=application.get("year_to"),
                    end_is_open=bool(application.get("end_is_open")),
                    verification_status=application.get("verification_status") or "confirmed",
                    payload={key: value for key, value in application.items() if key != "evidence"},
                )
                session.add(record); await session.flush()
            else:
                record.payload = {key: value for key, value in application.items() if key != "evidence"}
                record.updated_at = utcnow()
            evidence = application.get("evidence") or {}
            existing = (
                await session.execute(select(FitmentEvidence).where(
                    FitmentEvidence.fitment_id == record.id,
                    FitmentEvidence.source_key == evidence.get("source_key", ""),
                    FitmentEvidence.source_product_id == evidence.get("source_product_id", ""),
                    FitmentEvidence.parser_version == evidence.get("parser_version", ""),
                ))
            ).scalar_one_or_none()
            fetched = evidence.get("fetched_at")
            try:
                fetched_at = dt.datetime.fromisoformat(fetched) if fetched else utcnow()
            except ValueError:
                fetched_at = utcnow()
            if existing is None:
                session.add(FitmentEvidence(
                    fitment_id=record.id, source_key=evidence.get("source_key", ""),
                    source_product_id=evidence.get("source_product_id", ""),
                    source_url=evidence.get("source_url", ""), fetched_at=fetched_at,
                    parser_version=evidence.get("parser_version", ""),
                    raw_vehicle_label=evidence.get("raw_vehicle_label", ""),
                    raw_period=evidence.get("raw_period", ""),
                    match_basis=evidence.get("match_basis", "direct_product"),
                ))
            else:
                existing.source_url = evidence.get("source_url", "")
                existing.fetched_at = fetched_at
                existing.raw_vehicle_label = evidence.get("raw_vehicle_label", "")
                existing.raw_period = evidence.get("raw_period", "")
        await session.commit()
