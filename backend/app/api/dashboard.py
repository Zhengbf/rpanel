from fastapi import APIRouter, Depends, Query
from app.api.deps import get_current_user, get_router_client
from app.services.traffic import store
from app.adapters.ros.base import RouterOsClient
from app.services.sampler import detect_wan_interfaces
from app.db.session import AsyncSessionLocal
from sqlalchemy import select, func
from app.db.models import BlockedIp
from app.services.devices import DeviceService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/interfaces")
async def list_interfaces(
    user: dict = Depends(get_current_user),
    client: RouterOsClient = Depends(get_router_client),
):
    try:
        ifaces = await client.list_interfaces()
    except Exception:
        return []
    return [{"name": i.name, "type": i.type, "running": i.running,
             "disabled": i.disabled} for i in ifaces]


@router.get("/ip-addresses")
async def ip_addresses(
    user: dict = Depends(get_current_user),
    client: RouterOsClient = Depends(get_router_client),
):
    """接口 IP 信息（首页线路卡展示，支持 WAN IP 查看与隐藏）。"""
    try:
        return await client.get_ip_addresses()
    except Exception:
        return []


@router.get("/sys/history")
async def sys_history(
    window: str = Query("5m", pattern="^(5m|1h|24h)$"),
    user: dict = Depends(get_current_user),
):
    seconds = {"5m": 300, "1h": 3600, "24h": 86400}[window]
    return {
        "cpu": store.history("sys", "cpu", seconds),
        "mem": store.history("sys", "mem", seconds),
    }


@router.get("/wan/history")
async def wan_history(
    window: str = Query("5m", pattern="^(5m|1h|24h)$"),
    iface: str = "_total",
    points: int = Query(90, ge=30, le=300),
    user: dict = Depends(get_current_user),
    client: RouterOsClient = Depends(get_router_client),
):
    seconds = {"5m": 300, "1h": 3600, "24h": 86400}[window]
    return {"iface": iface, "window": window,
            "points": store.history("wan", iface, seconds, points)}


@router.get("/device/history")
async def device_history(
    ip: str,
    window: str = Query("5m", pattern="^(5m|1h|24h)$"),
    points: int = Query(90, ge=30, le=300),
    user: dict = Depends(get_current_user),
):
    seconds = {"5m": 300, "1h": 3600, "24h": 86400}[window]
    return {"ip": ip, "window": window,
            "points": store.history("device", ip, seconds, points)}


@router.get("/overview")
async def overview(
    user: dict = Depends(get_current_user),
    client: RouterOsClient = Depends(get_router_client),
):
    wan_ifaces: list[str] = []
    try:
        wan_ifaces = await detect_wan_interfaces(client)
    except Exception:
        pass
    try:
        res = await client.get_system_resource()
        identity = await client.get_identity()
        sys_ok = True
    except Exception:
        res = identity = None
        sys_ok = False

    ip_addresses = []
    try:
        ip_addresses = await client.get_ip_addresses()
    except Exception:
        pass

    svc = DeviceService(client)
    try:
        devices = await svc.list_devices()
    except Exception:
        devices = []
    online = [d for d in devices if d.online]
    total_rx = store.series("wan", "_total").last()

    per_iface = {}
    for name in wan_ifaces:
        last = store.series("wan", name).last()
        if last:
            per_iface[name] = {"rx": last[1], "tx": last[2]}

    async with AsyncSessionLocal() as db:
        blocked_count = (await db.execute(
            select(func.count(BlockedIp.ip)))).scalar() or 0

    mem_used = (res.total_memory - res.free_memory) if res else 0
    mem_total = res.total_memory if res else 0

    return {
        "router_connected": sys_ok,
        "identity": identity,
        "system": res.model_dump() if res else None,
        "mem_used": mem_used,
        "mem_total": mem_total,
        "device_count": len(devices),
        "online_count": len(online),
        "blocked_count": blocked_count,
        "current_rx": total_rx[1] if total_rx else 0,
        "current_tx": total_rx[2] if total_rx else 0,
        "wan_interfaces": wan_ifaces,
        "wan_rates": per_iface,
        "ip_addresses": ip_addresses,
        "disk_free": res.free_memory if res and hasattr(res, "free_hdd_space") else 0,
        "total_connections": len(devices and [] or []),
    }

