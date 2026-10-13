"""
网络管理服务（DHCP 等）。

设计说明（便于后续扩展）：
- 每个功能一个 service 模块，只依赖 RouterOsClient 协议，不关心 REST/SSH 差异
- 写操作统一在 api 层过 require_writable（只读模式）+ 这里写审计日志
- 返回值直接是给前端用的字典结构，字段名保持与前端契约稳定
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ros.base import RouterOsClient
from app.db.models import AuditLog

logger = logging.getLogger(__name__)


class NetworkService:
    def __init__(self, client: RouterOsClient):
        self.client = client

    async def dhcp_overview(self) -> dict:
        """DHCP 服务器 + 网段 + 地址池（网络页顶部信息区）。"""
        servers, networks, pools = await _gather(self.client)
        return {
            "servers": [s.model_dump() for s in servers],
            "networks": [n.model_dump() for n in networks],
            "pools": [p.model_dump() for p in pools],
        }

    async def provision_dhcp(self, db: AsyncSession, *, network_cidr: str, gateway: str,
                             pool_name: str, pool_ranges: str, server_name: str,
                             interface: str, dns_server: str, lease_time: str,
                             comment: str,
                             operator_id: int | None, operator_name: str) -> dict:
        """一站式创建一套可用的 DHCP 服务。

        顺序（这是 RouterOS 的硬性依赖，用户不该关心）：
            1. ip pool      —— 决定可分配地址范围
            2. dhcp network —— 决定客户端拿到的网关/DNS
            3. dhcp server  —— 把接口、地址池、租期绑起来
        已存在的同名/同网段对象会被复用，不重复创建，因此可安全重试。
        """
        steps: list[dict] = []

        # ---- 1. 地址池 ----
        # 只有「同名且范围一致」才复用；同名但范围不同说明是别人在用的池，
        # 直接改它会把现有网段的 DHCP 弄坏，因此明确报错让用户换个名字。
        pools = await _safe(self.client.list_ip_pools())
        existing_pool = next((p for p in pools if p.name == pool_name), None)
        if existing_pool:
            if (existing_pool.ranges or "").replace(" ", "") != pool_ranges.replace(" ", ""):
                raise ValueError(
                    f"地址池 {pool_name} 已存在且范围不同（现有 {existing_pool.ranges}）。"
                    f"请换一个地址池名，或先改成相同范围。"
                )
            steps.append({"step": "pool", "action": "exists", "name": pool_name,
                          "detail": existing_pool.ranges})
        else:
            await self.client.add_ip_pool(pool_name, pool_ranges,
                                          comment or f"created by router-panel for {server_name}")
            steps.append({"step": "pool", "action": "created", "name": pool_name,
                          "detail": pool_ranges})

        # ---- 2. 网段 ----
        # 网段的身份就是地址本身，同地址即同一对象，只补齐网关/DNS
        networks = await _safe(self.client.list_dhcp_networks())
        existing_net = next((n for n in networks if n.address == network_cidr), None)
        if existing_net:
            need_update = ((existing_net.gateway or "") != gateway) or \
                          (bool(dns_server) and (existing_net.dns_server or "") != dns_server)
            if need_update:
                await self.client.set_dhcp_network(existing_net.id, {
                    "gateway": gateway,
                    "dns_server": dns_server or existing_net.dns_server,
                })
                steps.append({"step": "network", "action": "updated", "name": network_cidr,
                              "detail": f"网关 {gateway} / DNS {dns_server or existing_net.dns_server}"})
            else:
                steps.append({"step": "network", "action": "exists", "name": network_cidr,
                              "detail": existing_net.gateway})
        else:
            await self.client.add_dhcp_network(network_cidr, gateway, "", dns_server, "",
                                               comment or "created by router-panel")
            steps.append({"step": "network", "action": "created", "name": network_cidr,
                          "detail": f"网关 {gateway} / DNS {dns_server or '—'}"})

        # ---- 3. DHCP 服务器 ----
        # 同名服务器只在「接口与地址池都一致」时复用；否则报错避免覆盖别人在用的服务
        servers = await _safe(self.client.list_dhcp_servers())
        existing_srv = next((x for x in servers if x.name == server_name), None)
        if existing_srv:
            same_target = (existing_srv.interface == interface
                           and (existing_srv.address_pool or "") == pool_name)
            if not same_target:
                raise ValueError(
                    f"DHCP 服务器 {server_name} 已存在且绑定的是"
                    f"接口 {existing_srv.interface} / 地址池 {existing_srv.address_pool or '（无）'}。"
                    f"请换一个服务器名，或先在路由器上确认后再操作。"
                )
            steps.append({"step": "server", "action": "exists", "name": server_name,
                          "detail": f"接口 {interface} / 地址池 {pool_name} / 租期 {existing_srv.lease_time}"})
        else:
            await self.client.add_dhcp_server(server_name, interface, pool_name, lease_time)
            steps.append({"step": "server", "action": "created", "name": server_name,
                          "detail": f"接口 {interface} / 地址池 {pool_name} / 租期 {lease_time}"})

        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_provision", target=server_name,
                        detail=f"network={network_cidr} pool={pool_name}({pool_ranges}) iface={interface}"))
        await db.commit()
        return {"ok": True, "steps": steps}

    async def pools(self) -> list[dict]:
        pools = await _safe(self.client.list_ip_pools())
        return [p.model_dump() for p in pools]

    async def add_pool(self, db: AsyncSession, name: str, ranges: str, comment: str,
                       operator_id: int | None, operator_name: str) -> dict:
        await self.client.add_ip_pool(name, ranges, comment)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_add_pool", target=name, detail=ranges))
        await db.commit()
        return {"ok": True, "name": name}

    async def set_pool(self, db: AsyncSession, pool_id: str, fields: dict,
                       operator_id: int | None, operator_name: str) -> dict:
        await self.client.set_ip_pool(pool_id, fields)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_set_pool", target=pool_id, detail=str(fields)))
        await db.commit()
        return {"ok": True, "pool_id": pool_id}

    async def remove_pool(self, db: AsyncSession, pool_id: str,
                          operator_id: int | None, operator_name: str) -> dict:
        await self.client.remove_ip_pool(pool_id)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_remove_pool", target=pool_id))
        await db.commit()
        return {"ok": True, "pool_id": pool_id}

    async def leases(self) -> list[dict]:
        """全部租约；标注动态/静态，供前端区分「可转静态」与「已静态」。"""
        try:
            leases = await self.client.list_leases()
        except Exception:
            logger.warning("读取 DHCP 租约失败", exc_info=True)
            return []
        out = []
        for lease in leases:
            out.append({
                "id": lease.id,
                "address": lease.address,
                "mac": lease.mac_address,
                "hostname": lease.host_name,
                "server": lease.server,
                "status": lease.status,
                "comment": lease.comment,
                "last_seen": lease.last_seen,
                "expires_after": lease.expires_after,
                "dynamic": lease.dynamic,
                "is_static": not lease.dynamic,
                "disabled": lease.disabled,
                "active": lease.active,
            })
        # 静态在前、其次按 IP 数值排序，便于查找
        out.sort(key=lambda x: (x["dynamic"], _ip_key(x["address"])))
        return out

    async def make_static(self, db: AsyncSession, lease_id: str,
                          operator_id: int | None, operator_name: str) -> dict:
        await self.client.make_lease_static(lease_id)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_make_static", target=lease_id))
        await db.commit()
        return {"ok": True, "lease_id": lease_id}

    async def add_static(self, db: AsyncSession, address: str, mac: str, server: str,
                         comment: str, operator_id: int | None, operator_name: str) -> dict:
        """新增静态绑定，并处理「该 MAC 已有动态租约」的常见情况。

        RouterOS 不允许同一 MAC 同时存在动态租约和静态绑定，直接 add 会失败。
        正确流程：
          1. 若该 MAC 已有动态租约 → 先 make-static 转成静态（保留当前 IP）
          2. 若目标 IP 与当前 IP 不同 → 再 set address 改到目标 IP
          3. 若该 MAC 没有租约 → 直接 add 一条静态绑定
        另外会先检查目标 IP 是否已被别的设备占用，避免产生冲突地址。
        """
        leases = []
        try:
            leases = await self.client.list_leases()
        except Exception:
            logger.warning("读取租约失败，按直接新增处理", exc_info=True)

        mac_up = mac.upper().replace("-", ":")
        same_mac = [l for l in leases if (l.mac_address or "").upper().replace("-", ":") == mac_up]
        conflict = [l for l in leases
                    if l.address == address and (l.mac_address or "").upper().replace("-", ":") != mac_up]
        if conflict:
            raise ValueError(f"{address} 已被 {conflict[0].mac_address} 占用")

        if same_mac:
            target = same_mac[0]
            if target.dynamic:
                await self.client.make_lease_static(target.id)
            if target.address != address:
                await self.client.set_lease(target.id, {"address": address})
            if comment:
                await self.client.set_lease(target.id, {"comment": comment})
        else:
            await self.client.add_static_lease(address, mac, server, comment)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_add_static", target=address,
                        detail=f"mac={mac} server={server} comment={comment}"))
        await db.commit()
        return {"ok": True, "address": address}

    async def add_server(self, db: AsyncSession, name: str, interface: str,
                         address_pool: str, lease_time: str,
                         operator_id: int | None, operator_name: str) -> dict:
        await self.client.add_dhcp_server(name, interface, address_pool, lease_time)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_add_server", target=name,
                        detail=f"interface={interface} pool={address_pool} lease={lease_time}"))
        await db.commit()
        return {"ok": True, "name": name}

    async def set_server(self, db: AsyncSession, server_id: str, fields: dict,
                         operator_id: int | None, operator_name: str) -> dict:
        await self.client.set_dhcp_server(server_id, fields)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_set_server", target=server_id, detail=str(fields)))
        await db.commit()
        return {"ok": True, "server_id": server_id}

    async def remove_server(self, db: AsyncSession, server_id: str,
                            operator_id: int | None, operator_name: str) -> dict:
        await self.client.remove_dhcp_server(server_id)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_remove_server", target=server_id))
        await db.commit()
        return {"ok": True, "server_id": server_id}

    async def add_network(self, db: AsyncSession, address: str, gateway: str, netmask: str,
                          dns_server: str, domain: str, comment: str,
                          operator_id: int | None, operator_name: str) -> dict:
        await self.client.add_dhcp_network(address, gateway, netmask, dns_server, domain, comment)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_add_network", target=address,
                        detail=f"gw={gateway} dns={dns_server}"))
        await db.commit()
        return {"ok": True, "address": address}

    async def set_network(self, db: AsyncSession, network_id: str, fields: dict,
                          operator_id: int | None, operator_name: str) -> dict:
        await self.client.set_dhcp_network(network_id, fields)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_set_network", target=network_id, detail=str(fields)))
        await db.commit()
        return {"ok": True, "network_id": network_id}

    async def remove_network(self, db: AsyncSession, network_id: str,
                             operator_id: int | None, operator_name: str) -> dict:
        await self.client.remove_dhcp_network(network_id)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_remove_network", target=network_id))
        await db.commit()
        return {"ok": True, "network_id": network_id}

    async def remove_lease(self, db: AsyncSession, lease_id: str,
                           operator_id: int | None, operator_name: str) -> dict:
        await self.client.remove_lease(lease_id)
        db.add(AuditLog(user_id=operator_id, username=operator_name,
                        action="dhcp_remove_lease", target=lease_id))
        await db.commit()
        return {"ok": True, "lease_id": lease_id}


async def _safe(coro):
    try:
        return await coro
    except Exception:
        return []


async def _gather(client: RouterOsClient):
    import asyncio

    servers, networks, pools = await asyncio.gather(
        _safe(client.list_dhcp_servers()),
        _safe(client.list_dhcp_networks()),
        _safe(client.list_ip_pools()),
    )
    return servers, networks, pools


def _ip_key(addr: str) -> tuple:
    parts = (addr or "").split(".")
    if len(parts) != 4:
        return (999, 999, 999, 999)
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (999, 999, 999, 999)
