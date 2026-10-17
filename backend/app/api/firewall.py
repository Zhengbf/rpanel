import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pydantic import IPvAnyAddress
from sqlalchemy import select
from app.api.deps import get_current_user, require_writable, get_router_client
from app.services.firewall import FirewallService
from app.services import firewall_scenes
from app.db.session import AsyncSessionLocal
from app.db.models import AuditLog, BlockedIp
from app.services.sampler import detect_wan_interfaces
from app.services.scope import current_device_id

router = APIRouter(prefix="/api/firewall", tags=["firewall"])


class BlockRequest(BaseModel):
    ip: IPvAnyAddress
    reason: str = Field("", max_length=256)


class PortSceneRequest(BaseModel):
    enable: bool
    protocol: str = Field("tcp", pattern="^(tcp|udp|both)$")
    ports: str = Field(..., min_length=1, max_length=64)
    wan: str = Field(..., min_length=1, max_length=64)


class LanSceneRequest(BaseModel):
    enable: bool


class WanSceneRequest(BaseModel):
    enable: bool
    family: str = Field("both", pattern="^(v4|v6|both)$")
    wan: str = Field(..., min_length=1, max_length=64)


_PORT_SPEC = re.compile(r"^\d{1,5}(-\d{1,5})?$")
_IFACE_SPEC = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _clean_ports(raw: str) -> str:
    """只接受 9233 或 8000-8100 两种写法，避免把任意字符串拼进规则。"""
    value = raw.strip().replace(" ", "")
    if not _PORT_SPEC.match(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "端口格式应为 9233 或 8000-8100")
    for part in value.split("-"):
        if not 1 <= int(part) <= 65535:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "端口范围应在 1-65535 之间")
    return value


def _clean_wan(raw: str) -> str:
    value = raw.strip()
    if not _IFACE_SPEC.match(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "WAN 接口名不合法")
    return value


async def _audit(user: dict, action: str, target: str, detail: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(AuditLog(user_id=user.get("user_id"), username=user.get("username"),
                        action=action, target=target, detail=detail))
        await db.commit()


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
        device_id = await current_device_id(db)
        if device_id is None:
            return []
        rows = (await db.execute(
            select(BlockedIp).where(BlockedIp.device_id == device_id)
        )).scalars().all()
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


# ---------------------------------------------------------------- 一键放通


@router.get("/scenes")
async def firewall_scenes_status(
    user: dict = Depends(get_current_user),
    client=Depends(get_router_client),
):
    """WAN/LAN 接口、现有规则，以及每个场景当前是否已放通。"""
    try:
        return await firewall_scenes.build_status(client)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"读取防火墙规则失败：{type(e).__name__}")


@router.post("/scenes/port")
async def firewall_scene_port(
    body: PortSceneRequest,
    user: dict = Depends(get_current_user),
    _: None = Depends(require_writable),
    client=Depends(get_router_client),
):
    ports = _clean_ports(body.ports)
    wan = _clean_wan(body.wan)
    protocols = ["tcp", "udp"] if body.protocol == "both" else [body.protocol]
    try:
        if body.enable:
            result = await firewall_scenes.allow_port(client, protocols, ports, wan)
        else:
            result = await firewall_scenes.revoke_port(client, protocols, ports, wan)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"路由器操作失败：{type(e).__name__}")
    await _audit(user, "fw_allow_port" if body.enable else "fw_revoke_port",
                 f"{wan}:{body.protocol}/{ports}",
                 f"created={result.get('created')} existed={result.get('existed')} "
                 f"removed={result.get('removed')}")
    return result


@router.post("/scenes/lan-all")
async def firewall_scene_lan_all(
    body: LanSceneRequest,
    user: dict = Depends(get_current_user),
    _: None = Depends(require_writable),
    client=Depends(get_router_client),
):
    try:
        result = await firewall_scenes.set_lan_all(client, body.enable)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"路由器操作失败：{type(e).__name__}")
    await _audit(user, "fw_lan_all_on" if body.enable else "fw_lan_all_off",
                 "lan-all", str(result))
    return result


@router.post("/scenes/wan-all")
async def firewall_scene_wan_all(
    body: WanSceneRequest,
    user: dict = Depends(get_current_user),
    _: None = Depends(require_writable),
    client=Depends(get_router_client),
):
    wan = _clean_wan(body.wan)
    try:
        result = await firewall_scenes.set_wan_all(client, body.enable, wan, body.family)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"路由器操作失败：{type(e).__name__}")
    await _audit(user, "fw_wan_all_on" if body.enable else "fw_wan_all_off",
                 f"{wan}/{body.family}", str(result))
    return result
