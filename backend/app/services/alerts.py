"""新设备接入告警 + 流量排行服务。"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import KnownDevice, TrafficHistory, AuditLog
from app.services.scope import current_device_id
from app.ws import hub


async def scan_for_new_devices(db: AsyncSession, devices: list) -> list[dict]:
    """对比已知 MAC 集合，登记新设备并返回未提醒的新设备列表。"""
    new_alerts: list[dict] = []
    device_id = await current_device_id(db)
    if device_id is None:
        return []
    known_macs: set[str] = set()
    rows = (await db.execute(
        select(KnownDevice).where(KnownDevice.device_id == device_id)
    )).scalars().all()
    known_macs = {r.mac for r in rows}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seen_this_batch: set[str] = set()
    for d in devices:
        if not d.mac:
            continue
        mac = d.mac.upper()
        # 同一批里同一 MAC 可能出现在多条记录中（DHCP 租约 + ARP，或同设备多 IP），
        # 必须去重，否则批量插入会撞 known_devices 的主键
        if mac in known_macs or mac in seen_this_batch:
            continue
        seen_this_batch.add(mac)
        db.add(KnownDevice(device_id=device_id, mac=mac, first_ip=d.ip,
                           hostname=d.hostname or None))
        new_alerts.append({
            "ip": d.ip, "mac": mac, "hostname": d.hostname or "",
            "first_seen": now.isoformat(),
        })
    if new_alerts:
        db.add(AuditLog(action="new_device", target=",".join(a["mac"] for a in new_alerts),
                        detail=str(new_alerts)))
    try:
        await db.commit()
    except IntegrityError:
        # 新设备扫描和设备列表可能同时打开两个会话；主键冲突说明另一个
        # 会话已经登记了同一批设备。这里重读后再合并，避免把一次普通
        # 并发扫描当成错误刷进日志。
        await db.rollback()
        rows = (await db.execute(
            select(KnownDevice).where(KnownDevice.device_id == device_id)
        )).scalars().all()
        known_macs = {r.mac for r in rows}
        new_alerts = [item for item in new_alerts if item["mac"] not in known_macs]
        for item in new_alerts:
            db.add(KnownDevice(device_id=device_id, mac=item["mac"],
                               first_ip=item["ip"], hostname=item["hostname"] or None))
        if new_alerts:
            db.add(AuditLog(action="new_device", target=",".join(a["mac"] for a in new_alerts),
                            detail=str(new_alerts)))
        await db.commit()

    # 未提醒的推 WebSocket
    unalerted = (await db.execute(
        select(KnownDevice).where(KnownDevice.device_id == device_id,
                                  KnownDevice.alerted == False)  # noqa: E712
    )).scalars().all()
    if unalerted:
        await hub.publish("alerts", {"new_devices": [
            {"mac": r.mac, "ip": r.first_ip, "hostname": r.hostname or ""} for r in unalerted
        ]})
    return new_alerts


async def ack_alerts(db: AsyncSession) -> int:
    device_id = await current_device_id(db)
    if device_id is None:
        return 0
    rows = (await db.execute(
        select(KnownDevice).where(KnownDevice.device_id == device_id,
                                  KnownDevice.alerted == False)  # noqa: E712
    )).scalars().all()
    for r in rows:
        r.alerted = True
    await db.commit()
    return len(rows)


async def traffic_ranking(db: AsyncSession, period: str = "today",
                          device_id: int | None = None) -> list[dict]:
    """设备流量排行（分钟级聚合）。period: today | 7d | 30d

    device_id 必传：同一批 IP 在不同路由器上是不同设备，
    不带设备维度聚合会把两台路由器的流量加在一起。
    """
    if period == "today":
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    elif period == "7d":
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    else:
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    conditions = [TrafficHistory.dimension == "device", TrafficHistory.ts >= start]
    if device_id is not None:
        conditions.append(TrafficHistory.device_id == device_id)
    rows = (await db.execute(
        select(TrafficHistory.key,
               func.sum(TrafficHistory.rx_bytes).label("rx"),
               func.sum(TrafficHistory.tx_bytes).label("tx"))
        .where(*conditions)
        .group_by(TrafficHistory.key)
        .order_by(func.sum(TrafficHistory.rx_bytes) + func.sum(TrafficHistory.tx_bytes) + func.sum(TrafficHistory.rx_bytes).desc())
        .limit(20)
    )).all()
    return [{"ip": r.key, "rx": int(r.rx or 0), "tx": int(r.tx or 0),
             "total": int(r.rx or 0) + int(r.tx or 0)} for r in rows]


async def cleanup_known_devices(db: AsyncSession, days: int = 90) -> None:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    await db.execute(delete(KnownDevice).where(KnownDevice.first_seen < cutoff))
    await db.commit()
