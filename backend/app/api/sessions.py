import time
import ipaddress
from fastapi import APIRouter, Depends, Query
from app.api.deps import get_current_user, get_router_client
from app.adapters.ros.base import RouterOsClient
from app.services.traffic import store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/{ip}")
async def device_sessions(
    ip: str,
    filter_proto: str = Query("", pattern="^(tcp|udp|)$"),
    search: str = Query("", max_length=64),
    user: dict = Depends(get_current_user),
    client: RouterOsClient = Depends(get_router_client),
):
    conns = await client.list_connections()
    sessions = []
    for c in conns:
        local = ""
        direction = ""
        if c.src_ip == ip:
            local, direction = c.src_ip, "out"
        elif c.dst_ip == ip:
            local, direction = c.dst_ip, "in"
        if not local:
            continue
        if filter_proto and c.protocol != filter_proto:
            continue
        if search and search not in (c.src_ip + c.dst_ip):
            continue
        sessions.append({
            "id": c.id,
            "protocol": c.protocol,
            "src": f"{c.src_ip}:{c.src_port or ''}",
            "dst": f"{c.dst_ip}:{c.dst_port or ''}",
            "direction": direction,
            "state": c.state,
            "tx_rate": 0.0,
            "rx_rate": 0.0,
            "total_bytes": c.total_bytes,
            "timeout": c.timeout,
        })
    sessions.sort(key=lambda s: -s["total_bytes"])
    curve = store.history("device", ip, 300.0)
    return {"ip": ip, "count": len(sessions), "sessions": sessions, "curve": curve}
