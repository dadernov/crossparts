from __future__ import annotations

import logging
import datetime as dt
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from . import groups as product_groups
from .aggregator import Aggregator
from .config import get_settings
from .db import SessionLocal, init_db
from .excel import (
    build_fitment_job_workbook, build_fitment_workbook, build_template, build_workbook, read_input,
)
from .fitment import FitmentService
from .fitment_jobs import FitmentJobRunner
from .jobs import JobRunner
from .models import (
    CacheEntry, FeatureEntitlement, FitmentEvidence, FitmentJob, FitmentPart, FitmentRecord,
    Job, JobItem, new_id, utcnow,
)
from .marketing import context as marketing_context
from .normalize import number_key
from .quota import quota_status, reserve_queries
from .schemas import (
    FitmentJobCreate, FitmentJobOut, FitmentLookupRequest, JobCreate, JobOut,
    LookupExportRequest, LookupRequest,
)
from .security import (
    authenticate, has_feature_access, is_guest_tenant, require_admin_fitment,
    require_search_access, require_tenant,
)
from .session import SignedSessionMiddleware
from .sources.registry import SourceRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()
registry = SourceRegistry(settings)
aggregator = Aggregator(settings, registry, SessionLocal)
runner = JobRunner(settings, aggregator, SessionLocal)
fitment = FitmentService(settings, SessionLocal)
fitment_runner = FitmentJobRunner(fitment, SessionLocal)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await runner.start()
    await fitment_runner.start()
    yield
    await fitment_runner.stop()
    await runner.stop()
    await registry.close()


app = FastAPI(
    title="CrossParts — поиск кроссов автозапчастей",
    version="0.1.0",
    description="B2B-сервис: по оригинальному номеру собирает кросс-номера из каталогов-источников.",
    lifespan=lifespan,
)
app.add_middleware(SignedSessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        status=job.status,
        total=job.total,
        done=job.done,
        sources=list(job.sources or []),
        filename=job.filename,
        created_at=job.created_at.isoformat(),
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


def _fitment_job_out(job: FitmentJob) -> FitmentJobOut:
    return FitmentJobOut(
        id=job.id, status=job.status, total=job.total,
        processed_count=job.processed_count, results=list(job.results or []),
        errors=list(job.errors or []), created_at=job.created_at.isoformat(),
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


# --------------------------------------------------------------------- UI

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    username = request.session.get("username")
    fitment_enabled = bool(
        username == "admin"
        and await has_feature_access(SessionLocal, username, "vehicle_fitment")
    )
    return templates.TemplateResponse(
        request,
        "index.html", {"sources": registry.describe(username), "settings": settings,
                        "username": username, "is_guest": not username,
                        "trial_active": bool(request.session.get("trial_active")),
                        "fitment_enabled": fitment_enabled,
                        "login_open": False, "login_error": None},
    )


@app.get("/features", response_class=HTMLResponse)
@app.get("/categories", response_class=HTMLResponse)
@app.get("/pricing", response_class=HTMLResponse)
@app.get("/integrations", response_class=HTMLResponse)
@app.get("/demo", response_class=HTMLResponse)
@app.get("/contacts", response_class=HTMLResponse)
async def marketing_page(request: Request):
    page = request.url.path.strip("/")
    return templates.TemplateResponse(request, "marketing-pages.html",
                                      marketing_context(registry, settings, page))


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("username"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "index.html",
        {"sources": registry.describe(), "settings": settings, "username": None,
         "is_guest": True, "trial_active": bool(request.session.get("trial_active")),
         "login_open": True, "login_error": None},
    )


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    account = await authenticate(SessionLocal, username, password)
    if account:
        request.session.clear()
        request.session["username"] = account
        request.session["access"] = "account"
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "index.html",
        {"sources": registry.describe(), "settings": settings, "username": username,
         "is_guest": True, "trial_active": bool(request.session.get("trial_active")),
         "login_open": True,
         "login_error": "Неверный логин или пароль"}, status_code=401,
    )


@app.post("/trial")
async def start_trial(request: Request):
    """Activate the caller's IP-bound free balance for this browser session."""
    if request.session.get("username"):
        return RedirectResponse("/", status_code=303)
    request.session["trial_active"] = True
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/template.xlsx")
async def download_template(tenant: str = Depends(require_tenant)):
    return Response(
        content=build_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="crossparts-template.xlsx"'},
    )


# ------------------------------------------------------------------- API

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/v1/sources")
async def list_sources(tenant: str = Depends(require_tenant)):
    sources = registry.describe(tenant)
    return {
        "sources": sources,
        "default": [source["key"] for source in sources if source["enabled_by_default"]],
    }


@app.get("/api/v1/groups")
async def list_groups(tenant: str = Depends(require_tenant)):
    """Товарные группы и покрытие каталогами — какой сайт какую группу закрывает."""
    return {"groups": registry.coverage()}


@app.get("/api/v1/account")
async def account_status(tenant: str = Depends(require_tenant)):
    """The remaining search positions for the signed-in client."""
    limit = settings.trial_requests if is_guest_tenant(tenant) else settings.requests_per_account
    return await quota_status(SessionLocal, tenant, limit)


@app.post("/api/v1/lookup")
async def lookup(req: LookupRequest, tenant: str = Depends(require_search_access)):
    """Single OE number, answered synchronously."""
    group = product_groups.resolve(req.group) if req.group else None
    limit = settings.trial_requests if is_guest_tenant(tenant) else settings.requests_per_account
    await reserve_queries(SessionLocal, tenant, 1, limit)
    result = await aggregator.lookup(
        req.oe, req.sources, use_cache=True, group=group, tenant=tenant
    )
    # Persist the result already fetched: no second lookup or quota charge.
    async with SessionLocal() as session:
        job = Job(tenant=tenant, status="done", total=1, done=1,
                  filename=f"Поиск · {req.oe}"[:255],
                  sources=[source["source"] for source in result["sources"]],
                  finished_at=utcnow())
        session.add(job)
        await session.flush()
        session.add(JobItem(job_id=job.id, position=0, oe_number=req.oe,
                            group=group, group_raw=req.group,
                            status=result["status"], crosses=result["crosses"],
                            source_reports=result["sources"]))
        await session.commit()
    return result


@app.post("/api/v1/lookup/export.xlsx")
async def lookup_export(payload: LookupExportRequest, tenant: str = Depends(require_tenant)):
    """Export the result already shown for one OE lookup without running it again."""
    blob = build_workbook([{
        "our_sku": "",
        "oe_number": payload.oe_number,
        "group": product_groups.resolve(payload.group) if payload.group else None,
        "group_raw": payload.group_raw,
        "crosses": [cross.model_dump() for cross in payload.crosses],
    }], include_our_sku=False)
    filename = number_key(payload.oe_number)[:40] or "lookup"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="crosses-{filename}.xlsx"'},
    )


@app.post("/api/v1/fitment/lookup")
async def fitment_lookup(
    payload: FitmentLookupRequest,
    tenant: str = Depends(require_admin_fitment),
):
    """Explicit pilot enrichment; the dependency and UI are admin-only."""
    if tenant != "admin":
        raise HTTPException(403, "Модуль применяемости доступен только admin")
    if payload.group != product_groups.SHOCK_ABSORBERS:
        raise HTTPException(400, "Пилот применяемости работает только для амортизаторов")
    brand = payload.brand.strip().upper()
    if brand not in fitment.supported_brands:
        raise HTTPException(400, "Для этого бренда источник применяемости не подключён")
    return await fitment.lookup(brand, payload.number)


@app.post("/api/v1/fitment/export.xlsx")
async def fitment_export(
    payload: FitmentLookupRequest,
    tenant: str = Depends(require_admin_fitment),
):
    """Download the same cached applicability card as a standalone workbook."""
    if tenant != "admin":
        raise HTTPException(403, "Модуль применяемости доступен только admin")
    if payload.group != product_groups.SHOCK_ABSORBERS:
        raise HTTPException(400, "Пилот применяемости работает только для амортизаторов")
    brand = payload.brand.strip().upper()
    if brand not in fitment.supported_brands:
        raise HTTPException(400, "Для этого бренда источник применяемости не подключён")
    result = await fitment.lookup(brand, payload.number)
    if result["status"] != "ok":
        raise HTTPException(404, result.get("message") or "Применяемость не найдена")
    filename = f"fitment-{brand.lower()}-{number_key(payload.number)[:40]}.xlsx"
    return Response(
        content=build_fitment_workbook(result),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/v1/fitment/jobs", response_model=FitmentJobOut)
async def create_fitment_job(
    payload: FitmentJobCreate,
    tenant: str = Depends(require_admin_fitment),
):
    """Queue an explicit batch; it never walks cross numbers automatically."""
    async with SessionLocal() as session:
        grant = await session.get(FeatureEntitlement, f"{tenant}:vehicle_fitment")
    grant_limit = int((grant.limits or {}).get("max_parts_per_job", settings.fitment_max_parts_per_job))
    max_parts = min(settings.fitment_max_parts_per_job, max(1, grant_limit))
    if len(payload.parts) > max_parts:
        raise HTTPException(400, f"В одном задании применяемости разрешено не более {max_parts} деталей")
    if payload.idempotency_key:
        async with SessionLocal() as session:
            existing = (await session.execute(select(FitmentJob).where(
                FitmentJob.tenant == tenant,
                FitmentJob.idempotency_key == payload.idempotency_key,
            ))).scalar_one_or_none()
            if existing is not None:
                return _fitment_job_out(existing)
    parts, seen = [], set()
    for raw in payload.parts:
        brand = raw.brand.strip().upper()
        group = product_groups.resolve(raw.group)
        key = (brand, number_key(raw.number), group)
        if group != product_groups.SHOCK_ABSORBERS:
            raise HTTPException(400, "Пилот применяемости работает только для амортизаторов")
        if brand not in fitment.supported_brands:
            raise HTTPException(400, f"Источник применяемости {brand} не подключён")
        if key not in seen:
            seen.add(key); parts.append({"brand": brand, "number": raw.number, "group": group})
    job = FitmentJob(
        tenant=tenant, status="queued", idempotency_key=payload.idempotency_key,
        requested_parts=parts, total=len(parts), processed_count=0,
    )
    async with SessionLocal() as session:
        session.add(job)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            if not payload.idempotency_key:
                raise
            job = (await session.execute(select(FitmentJob).where(
                FitmentJob.tenant == tenant,
                FitmentJob.idempotency_key == payload.idempotency_key,
            ))).scalar_one()
            return _fitment_job_out(job)
        await session.refresh(job)
    await fitment_runner.submit(job.id)
    return _fitment_job_out(job)


@app.get("/api/v1/fitment/jobs/{job_id}", response_model=FitmentJobOut)
async def get_fitment_job(job_id: str, tenant: str = Depends(require_admin_fitment)):
    async with SessionLocal() as session:
        job = await session.get(FitmentJob, job_id)
    if job is None or job.tenant != tenant:
        raise HTTPException(404, "Задание применяемости не найдено")
    return _fitment_job_out(job)


@app.post("/api/v1/fitment/jobs/{job_id}/cancel", response_model=FitmentJobOut)
async def cancel_fitment_job(job_id: str, tenant: str = Depends(require_admin_fitment)):
    async with SessionLocal() as session:
        job = await session.get(FitmentJob, job_id)
        if job is None or job.tenant != tenant:
            raise HTTPException(404, "Задание применяемости не найдено")
        if job.status in {"queued", "running"}:
            job.cancel_requested = True
            await session.commit(); await session.refresh(job)
    return _fitment_job_out(job)


@app.get("/api/v1/fitment/jobs/{job_id}/export.xlsx")
async def export_fitment_job(job_id: str, tenant: str = Depends(require_admin_fitment)):
    async with SessionLocal() as session:
        job = await session.get(FitmentJob, job_id)
    if job is None or job.tenant != tenant:
        raise HTTPException(404, "Задание применяемости не найдено")
    if job.status not in {"done", "partial", "failed"}:
        raise HTTPException(409, "Задание ещё не завершено")
    return Response(
        content=build_fitment_job_workbook(list(job.results or [])),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="fitment-{job.id}.xlsx"'},
    )


@app.get("/api/v1/fitment/metrics")
async def fitment_metrics(tenant: str = Depends(require_admin_fitment)):
    async with SessionLocal() as session:
        counts = {}
        for name, model in (("parts", FitmentPart), ("records", FitmentRecord),
                            ("evidence", FitmentEvidence), ("jobs", FitmentJob)):
            counts[name] = (await session.execute(select(func.count()).select_from(model))).scalar_one()
        cache_rows = (await session.execute(select(func.count()).select_from(CacheEntry).where(
            CacheEntry.source.like("fitment:%")
        ))).scalar_one()
    return {**counts, "cache_entries": cache_rows,
            "runtime_sources": fitment.metrics_snapshot(),
            "supported_brands": list(fitment.supported_brands), "pilot_tenant": tenant}


@app.post("/api/v1/jobs", response_model=JobOut)
async def create_job(payload: JobCreate, tenant: str = Depends(require_search_access)):
    if not payload.items:
        raise HTTPException(400, "Пустой список позиций")
    return await _create_job(
        [i.model_dump() for i in payload.items], payload.sources, tenant, None
    )


@app.post("/api/v1/jobs/upload", response_model=JobOut)
async def upload_job(
    file: UploadFile = File(...),
    sources: str | None = Form(default=None),
    tenant: str = Depends(require_search_access),
):
    """Upload the client's xlsx: column «Наш Артикул» + column «Номер ОЕ»."""
    data = await file.read()
    try:
        items = read_input(data)
    except Exception as exc:
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}") from exc
    if not items:
        raise HTTPException(400, "В файле не найдено ни одной строки с номером ОЕ")
    keys = [s.strip() for s in (sources or "").split(",") if s.strip()] or None
    return await _create_job(items, keys, tenant, file.filename)


async def _create_job(items, sources, tenant, filename) -> JobOut:
    chosen = [s.key for s in registry.select_for_job(sources, tenant=tenant)]
    if not chosen:
        raise HTTPException(400, "Не выбран ни один известный источник")
    limit = settings.trial_requests if is_guest_tenant(tenant) else settings.requests_per_account
    await reserve_queries(SessionLocal, tenant, len(items), limit)
    chunk_size = settings.job_chunk_size_for(tenant)
    if chunk_size and len(items) > chunk_size:
        return await _create_split_jobs(items, chosen, tenant, filename, chunk_size)
    async with SessionLocal() as session:
        job = Job(tenant=tenant, sources=chosen, total=len(items), filename=filename)
        session.add(job)
        await session.flush()
        _add_job_items(session, job.id, items)
        await session.commit()
        out = _job_out(job)
    await runner.submit(out.id)
    return out


async def _create_split_jobs(items, chosen, tenant, filename, chunk_size) -> JobOut:
    chunks = [items[pos:pos + chunk_size] for pos in range(0, len(items), chunk_size)]
    batch_id = new_id()
    base_name = filename or "Задание из API"
    created = utcnow()
    jobs = {}
    async with SessionLocal() as session:
        # Insert in reverse display order: part 1 is initially the newest entry.
        for index in reversed(range(len(chunks))):
            chunk = chunks[index]
            job = Job(
                tenant=tenant,
                sources=chosen,
                total=len(chunk),
                filename=f"{base_name} · часть {index + 1}/{len(chunks)}"[:255],
                created_at=created + dt.timedelta(microseconds=len(chunks) - index),
                batch_id=batch_id,
                batch_role="chunk",
                batch_order=index,
            )
            session.add(job)
            await session.flush()
            _add_job_items(session, job.id, chunk, position_offset=index * chunk_size)
            jobs[index] = job
        await session.commit()
        first = _job_out(jobs[0])
    await runner.submit(first.id)
    return first


def _add_job_items(session, job_id, items, position_offset=0) -> None:
    for pos, item in enumerate(items, start=position_offset):
        raw = item.get("group_raw") or item.get("group") or ""
        session.add(JobItem(
            job_id=job_id,
            position=pos,
            our_sku=item.get("our_sku", ""),
            part_name=item.get("part_name", ""),
            oe_number=item["oe_number"],
            group=item.get("group") or product_groups.resolve(raw),
            group_raw=raw or None,
        ))


@app.get("/api/v1/jobs", response_model=list[JobOut])
async def list_jobs(tenant: str = Depends(require_tenant), limit: int = 50):
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Job).where(Job.tenant == tenant)
                .order_by(Job.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        return [_job_out(j) for j in rows]


async def _load_job(job_id: str, tenant: str) -> tuple[Job, list[JobItem]]:
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None or job.tenant != tenant:
            raise HTTPException(404, "Задание не найдено")
        items = (
            await session.execute(
                select(JobItem).where(JobItem.job_id == job_id).order_by(JobItem.position)
            )
        ).scalars().all()
        return job, items


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str, tenant: str = Depends(require_tenant)):
    job, items = await _load_job(job_id, tenant)
    return {
        "job": _job_out(job).model_dump(),
        "items": [
            {
                "our_sku": i.our_sku,
                "part_name": i.part_name,
                "oe_number": i.oe_number,
                "group": i.group,
                "group_title": product_groups.title(i.group) if i.group else (i.group_raw or "—"),
                "status": i.status,
                "crosses_count": len(i.crosses or []),
            }
            for i in items
        ],
    }


@app.get("/api/v1/jobs/{job_id}/results")
async def job_results(job_id: str, format: str = "long", tenant: str = Depends(require_tenant)):
    """``format=long`` → вариант 1 (строка на кросс); ``wide`` → вариант 2."""
    _, items = await _load_job(job_id, tenant)
    if format == "wide":
        return {
            "rows": [
                {
                    "our_sku": i.our_sku,
                    "part_name": i.part_name,
                    "group": i.group,
                    "oe_number": i.oe_number,
                    "crosses": _unique_numbers(i.crosses or []),
                }
                for i in items
            ]
        }
    rows = []
    for i in items:
        for c in i.crosses or []:
            rows.append({
                "our_sku": i.our_sku,
                "part_name": i.part_name,
                "group": i.group,
                "oe_number": i.oe_number,
                "brand": c["brand"],
                "number": c["number"],
                "kind": c.get("kind"),
                "sources": c.get("sources", []),
            })
    return {"rows": rows}


@app.get("/api/v1/jobs/{job_id}/export.xlsx")
async def job_export(job_id: str, tenant: str = Depends(require_tenant)):
    job, items = await _load_job(job_id, tenant)
    payload = [
        {
            "our_sku": i.our_sku,
            "part_name": i.part_name,
            "oe_number": i.oe_number,
            "group": i.group,
            "group_raw": i.group_raw,
            "status": i.status,
            "crosses": i.crosses or [],
            "source_reports": i.source_reports or [],
        }
        for i in items
    ]
    blob = build_workbook(payload)
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="crosses-{job.id[:8]}.xlsx"'},
    )


def _unique_numbers(crosses: list[dict]) -> list[str]:
    from .normalize import number_key

    seen, out = set(), []
    for c in crosses:
        k = number_key(c["number"])
        if k not in seen:
            seen.add(k)
            out.append(c["number"])
    return out
