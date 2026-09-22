from unittest.mock import AsyncMock
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from fastapi import HTTPException
from app import main
from app.models import Base
from app.schemas import LookupRequest

@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['ok','partial','not_found','blocked'])
async def test_single_lookup_saved_once_and_isolated(tmp_path, monkeypatch, status):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/history.db')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main, 'SessionLocal', sessions)
    charge = AsyncMock()
    monkeypatch.setattr(main, 'reserve_queries', charge)
    result = {'oe':'58101H5A25','status':status,'crosses':[{'brand':'NiBK','number':'PN0537','sources':['brixo']}] if status=='ok' else [], 'sources':[{'source':'brixo','status':status,'crosses':[]}]}
    lookup = AsyncMock(return_value=result)
    monkeypatch.setattr(main.aggregator, 'lookup', lookup)
    assert await main.lookup(LookupRequest(oe='58101H5A25',group='brake_pads'),tenant='alice') == result
    charge.assert_awaited_once()
    lookup.assert_awaited_once()
    jobs = await main.list_jobs(tenant='alice')
    assert len(jobs)==1 and jobs[0].done==1 and jobs[0].status=='done'
    assert await main.list_jobs(tenant='bob') == []
    with pytest.raises(HTTPException) as error:
        await main.get_job(jobs[0].id,tenant='bob')
    assert error.value.status_code==404
    detail=await main.get_job(jobs[0].id,tenant='alice')
    assert detail['items'][0]['status']==status
    rows=await main.job_results(jobs[0].id,tenant='alice')
    assert len(rows['rows'])==len(result['crosses'])
    export=await main.job_export(jobs[0].id,tenant='alice')
    assert export.body[:2]==b'PK'
    await engine.dispose()
