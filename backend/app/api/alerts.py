from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from app.api.deps import get_current_user, get_router_client, get_current_device_id
from app.db.session import AsyncSessionLocal
from app.services.alerts import ack_alerts, traffic_ranking
from app.services.devices import DeviceService
from app.adapters.ros.base import RouterOsClient

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/new-devices")
async def new_devices(user: dict = Depends(get_current_user)):
    """未确认的新设备告警。"""
    from app.db.models import KnownDevice
    from app.services.scope import current_device_id
    async with AsyncSessionLocal() as db:
        device_id = await current_device_id(db)
        if device_id is None:
            return []
        rows = (await db.execute(
            select(KnownDevice).where(KnownDevice.device_id == device_id,
                                      KnownDevice.alerted == False)  # noqa: E712
        )).scalars().all()
    return [{"mac": r.mac, "ip": r.first_ip, "hostname": r.hostname or "",
             "first_seen": str(r.first_seen)} for r in rows]


@router.post("/ack")
async def ack(user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        n = await ack_alerts(db)
    return {"acked": n}


@router.get("/ranking")
async def ranking(
    period: str = Query("today", pattern="^(today|7d|30d)$"),
    user: dict = Depends(get_current_user),
    client: RouterOsClient = Depends(get_router_client),
    device_id: int | None = Depends(get_current_device_id),
):
    """设备流量排行（真实数据，来自分钟级聚合）。"""
    async with AsyncSessionLocal() as db:
        return await traffic_ranking(db, period, device_id)
