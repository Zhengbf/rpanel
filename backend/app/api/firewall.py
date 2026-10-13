from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pydantic import IPvAnyAddress
from sqlalchemy import select
from app.api.deps import get_current_user, require_writable, get_router_client
from app.services.firewall import FirewallService
from app.db.session import AsyncSessionLocal
from app.db.models import BlockedIp
from app.services.sampler import detect_wan_interfaces

router = APIRouter(prefix="/api/firewall", tags=["firewall"])


class BlockRequest(BaseModel):
    ip: IPvAnyAddress
    reason: str = Field("", max_length=256)


async def _get_wan_ifaces(client) -> list[str]:
    """封禁规则不限定 out-interface，用空列表即可；保留检测用于未来精细化。"""
    try:
        return await detect_wan_interfaces(client)
    except Exception:
        return []


@router.post("/block")
async def block_ip(
    body: BlockRequest,
    user: dict = Depends(get_current_user),
    _: None = Depends(require_writable),
    client=Depends(get_router_client),
):
    wan = await _get_wan_ifaces(client)
    svc = FirewallService(client, wan)
    async with AsyncSessionLocal() as db:
        try:
            await svc.block_ip(db, str(body.ip), user["user_id"],
                               user["username"], body.reason)
        except PermissionError as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
        except Exception as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"路由器操作失败：{type(e).__name__}")
    return {"ok": True, "ip": str(body.ip)}


@router.post("/unblock")
async def unblock_ip(
    body: BlockRequest,
    user: dict = Depends(get_current_user),
    _: None = Depends(require_writable),
    client=Depends(get_router_client),
):
    wan = await _get_wan_ifaces(client)
    svc = FirewallService(client, wan)
    async with AsyncSessionLocal() as db:
        try:
            await svc.unblock_ip(db, str(body.ip), user["user_id"], user["username"])
        except PermissionError as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
        except Exception as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"路由器操作失败：{type(e).__name__}")
    return {"ok": True, "ip": str(body.ip)}


@router.get("/blocked")
async def list_blocked(
    user: dict = Depends(get_current_user),
    client=Depends(get_router_client),
):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(BlockedIp))).scalars().all()
    return [{"ip": r.ip, "reason": r.reason, "blocked_by": r.blocked_by,
             "blocked_at": str(r.blocked_at)} for r in rows]


@router.post("/reconcile")
async def reconcile(
    user: dict = Depends(get_current_user),
    client=Depends(get_router_client),
):
    wan = await _get_wan_ifaces(client)
    svc = FirewallService(client, wan)
    async with AsyncSessionLocal() as db:
        result = await svc.reconcile(db)
    return result
