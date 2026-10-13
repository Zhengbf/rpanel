from __future__ import annotations
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import BlockedIp, AuditLog
from app.adapters.ros.base import RouterOsClient
from app.config import settings
from app.services.sampler import detect_wan_interfaces
from app.services.scope import current_device_id

logger = logging.getLogger(__name__)


class FirewallService:
    def __init__(self, client: RouterOsClient, wan_ifaces: list[str]):
        self.client = client
        self.wan_ifaces = wan_ifaces

    async def _current_wan(self) -> list[str]:
        """每次操作前重新检测 WAN 口，适配不同设备/接口变化。"""
        try:
            return await detect_wan_interfaces(self.client) or self.wan_ifaces
        except Exception:
            return self.wan_ifaces

    async def block_ip(self, db: AsyncSession, ip: str,
                       operator_id: int, operator_name: str,
                       reason: str = "") -> None:
        if settings.readonly_mode:
            raise PermissionError("只读模式，禁止封禁操作")
        device_id = await current_device_id(db)
        if device_id is None:
            raise PermissionError("尚未绑定路由器设备，无法封禁")
        wan = await self._current_wan()
        await self.client.add_block(ip, wan)
        await self.client.clear_connections(ip)
        existing = await db.get(BlockedIp, (device_id, ip))
        if existing is None:
            db.add(BlockedIp(device_id=device_id, ip=ip, reason=reason,
                             blocked_by=operator_name))
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="block_ip", target=ip, detail=reason))
        await db.commit()

    async def unblock_ip(self, db: AsyncSession, ip: str,
                         operator_id: int, operator_name: str) -> None:
        if settings.readonly_mode:
            raise PermissionError("只读模式，禁止解封操作")
        device_id = await current_device_id(db)
        if device_id is None:
            raise PermissionError("尚未绑定路由器设备，无法解封")
        wan = await self._current_wan()
        await self.client.remove_block(ip, wan)
        existing = await db.get(BlockedIp, (device_id, ip))
        if existing:
            await db.delete(existing)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="unblock_ip", target=ip))
        await db.commit()

    async def reconcile(self, db: AsyncSession) -> dict:
        device_id = await current_device_id(db)
        if device_id is None:
            raise PermissionError("尚未绑定路由器设备，无法对账")
        router_blocked = set(await self.client.list_blocked())
        # 只对账"当前这台设备"的记录；别的路由器的封禁列表原样保留
        local_rows = (await db.execute(
            select(BlockedIp).where(BlockedIp.device_id == device_id)
        )).scalars().all()
        local_ips = {r.ip for r in local_rows}

        added = router_blocked - local_ips
        removed = local_ips - router_blocked
        for ip in added:
            db.add(BlockedIp(device_id=device_id, ip=ip, reason="reconcile-from-router"))
        for r in list(local_rows):
            if r.ip in removed:
                await db.delete(r)
        if added or removed:
            db.add(AuditLog(action="reconcile", target="blocked_ips",
                            detail=f"+{sorted(added)} -{sorted(removed)}"))
        await db.commit()
        return {"router": sorted(router_blocked), "added": sorted(added),
                "removed": sorted(removed)}
