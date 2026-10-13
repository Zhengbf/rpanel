"""当前被管理的路由器（默认设备）解析。

封禁列表、设备备注、新设备记录、流量历史都要按设备分开存，
所有读写都必须先拿到"现在是哪台"，否则换绑后数据会串台。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RouterDevice


async def current_device_id(db: AsyncSession) -> int | None:
    """当前默认设备的 id；没有绑定设备时返回 None。"""
    dev = (await db.execute(
        select(RouterDevice).where(RouterDevice.is_default == True)  # noqa: E712
    )).scalar_one_or_none()
    return dev.id if dev else None
