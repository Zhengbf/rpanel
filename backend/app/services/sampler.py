from __future__ import annotations
import asyncio
import time
import logging
from app.adapters.ros.base import RouterOsClient
from app.services.traffic import store
from app.services.devices import _private_ip
from app.db.session import AsyncSessionLocal
from app.ws import hub
from app.config import settings

logger = logging.getLogger(__name__)


async def detect_wan_interfaces(client: RouterOsClient) -> list[str]:
    """自动识别 WAN 出口线路。

    只保留“最上层”接口：PPPoE 建在 VLAN 上、VLAN 建在物理口上时，
    三层会统计到同一份流量，必须去重，否则总带宽翻倍。
    """
    try:
        ifaces = await client.list_interfaces()
    except Exception:
        return []

    # 父接口关系：pppoe-client.interface / vlan.interface
    parents: dict[str, str] = {}
    for path, child_key in (("/interface/pppoe-client", "name"), ("/interface/vlan", "name")):
        try:
            raw = await client._get(path)  # type: ignore[attr-defined]
        except Exception:
            continue
        if isinstance(raw, list):
            for r in raw:
                child, parent = r.get(child_key), r.get("interface")
                if child and parent:
                    parents[child] = parent

    candidates: list[str] = []
    for i in ifaces:
        if i.disabled:
            continue
        t, n = i.type.lower(), i.name.lower()
        if any(k in n for k in ("bridge", "loopback")) or n in ("lo",):
            continue
        if any(k in t for k in ("pppoe", "vlan")) or any(k in n for k in ("wan", "pppoe", "wg", "vlan")):
            candidates.append(i.name)
    if not candidates:
        candidates = [i.name for i in ifaces if i.running and not i.disabled]

    # 去掉作为其他候选接口父级的接口（例如 vlan10-tel 是 pppoe-wan1 的父级）
    ancestors = set()
    for c in candidates:
        p = parents.get(c)
        depth = 0
        while p and depth < 5:
            ancestors.add(p)
            p = parents.get(p)
            depth += 1
    result = [c for c in candidates if c not in ancestors]
    return result or candidates


TUNNEL_HINTS = ("wg", "ovpn", "l2tp", "pptp", "sstp", "ike", "ipip", "gre", "eovpn", "vxlan")


async def detect_tunnel_interfaces(client: RouterOsClient, wans: list[str]) -> set[str]:
    """隧道类接口：流量已封装在物理 WAN 内，不能再计入总量。"""
    tunnels: set[str] = set()
    try:
        ifaces = await client.list_interfaces()
    except Exception:
        return tunnels
    for i in ifaces:
        t, n = i.type.lower(), i.name.lower()
        if any(k in t for k in ("wg", "ovpn", "l2tp", "pptp", "sstp", "gre", "ipip", "vxlan")) \
           or n.startswith(tuple(k + "-" for k in TUNNEL_HINTS)) or n in TUNNEL_HINTS:
            if i.name in wans:
                tunnels.add(i.name)
    return tunnels


class Sampler:
    def __init__(self, client: RouterOsClient):
        self.client = client
        self.interval = settings.sample_interval
        self.wan_ifaces: list[str] = []
        self.total_ifaces: list[str] = []
        self._prev_conns: dict[str, tuple[float, int, int]] = {}
        self._prev_ip: dict[str, tuple[float, int, int]] = {}
        self.connected = False          # 路由器是否可达（最近一次采样结果）
        self.last_sample_ts: float = 0.0
        self._task: asyncio.Task | None = None
        self._minute_task: asyncio.Task | None = None
        self.running = False

    async def start(self) -> None:
        self.running = True
        self.wan_ifaces = await detect_wan_interfaces(self.client)
        tunnels = await detect_tunnel_interfaces(self.client, self.wan_ifaces)
        self.total_ifaces = [w for w in self.wan_ifaces if w not in tunnels]
        logger.info("WAN interfaces: %s (计入总量的: %s)", self.wan_ifaces, self.total_ifaces)
        # 先立即采样一次，避免用户刚绑定完看到一片空白
        try:
            await self._sample_once()
            self.connected = True
            await hub.publish("router_status", {"connected": True})
        except Exception:
            logger.warning("首次采样失败", exc_info=True)
        self._task = asyncio.create_task(self._loop())
        self._minute_task = asyncio.create_task(self._minute_loop())

    async def stop(self) -> None:
        self.running = False
        for t in (self._task, self._minute_task):
            if t:
                t.cancel()

    async def _loop(self) -> None:
        while self.running:
            try:
                await self._sample_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("采样失败")
                self.connected = False
                await hub.publish("router_status", {"connected": False})
            await asyncio.sleep(self.interval)

    async def _sample_once(self) -> None:
        wan_data: dict[str, dict] = {}
        now = time.time()
        counters = await self.client.get_interface_counters()
        prev_wan = getattr(self, "_prev_wan_counters", {})
        for iface in self.wan_ifaces:
            cur = counters.get(iface)
            prev = prev_wan.get(iface)
            if not cur or not prev or now <= prev[0]:
                rx = tx = 0.0
            else:
                dt = now - prev[0]
                rx = max(0.0, (cur["rx"] - prev[1]) / dt)
                tx = max(0.0, (cur["tx"] - prev[2]) / dt)
            if cur:
                self._prev_wan_counters = getattr(self, "_prev_wan_counters", {})
                self._prev_wan_counters[iface] = (now, cur["rx"], cur["tx"])
            store.push_sample("wan", iface, rx, tx)
            wan_data[iface] = {"rx": rx, "tx": tx}
        total_rx = sum(wan_data[w]["rx"] for w in self.total_ifaces if w in wan_data)
        total_tx = sum(wan_data[w]["tx"] for w in self.total_ifaces if w in wan_data)
        store.push_sample("wan", "_total", total_rx, total_tx)

        conns = await self.client.list_connections()
        now = time.time()

        session_rates: dict[str, dict] = {}
        for c in conns:
            p = self._prev_conns.get(c.id)
            if p and now > p[0]:
                dt = now - p[0]
                session_rates[c.id] = {
                    "tx": max(0.0, (c.orig_bytes - p[1]) / dt),
                    "rx": max(0.0, (c.reply_bytes - p[2]) / dt),
                }

        # 归属：src / dst / reply-src / reply-dst 四个地址都可能是内网主机
        # （NAT 后入站连接的内网主机在 reply-src-address）
        cur: dict[str, tuple[int, int]] = {}
        rate_by_ip: dict[str, list[float]] = {}
        sessions_by_ip: dict[str, int] = {}
        for c in conns:
            local = None
            for cand in (c.src_ip, c.dst_ip, c.reply_src_ip, c.reply_dst_ip):
                if cand and _private_ip(cand):
                    local = cand
                    break
            if local is None:
                continue
            o, r = cur.get(local, (0, 0))
            cur[local] = (o + c.orig_bytes, r + c.reply_bytes)
            sessions_by_ip[local] = sessions_by_ip.get(local, 0) + 1
            agg = rate_by_ip.setdefault(local, [0.0, 0.0])
            agg[0] += c.orig_rate
            agg[1] += c.repl_rate

        devices_msg = []
        for ip, (o_total, r_total) in cur.items():
            p_ip = self._prev_ip.get(ip)
            if p_ip and now > p_ip[0]:
                dt = now - p_ip[0]
                tx_diff = max(0.0, (o_total - p_ip[1]) / dt)
                rx_diff = max(0.0, (r_total - p_ip[2]) / dt)
            else:
                tx_diff = rx_diff = 0.0
            # 优先用连接字节数差分。RouterOS connection 的 orig-rate/repl-rate
            # 只反映当前采样间隔内的会话速率，fasttrack 长连接经常保持旧值或 0，
            # 直接优先它会导致终端速率远低于 WAN。
            tx_rate = tx_diff
            rx_rate = rx_diff
            if tx_rate == 0 and rx_rate == 0:
                tx_rate_live, rx_rate_live = rate_by_ip.get(ip, [0.0, 0.0])
                tx_rate = tx_rate_live
                rx_rate = rx_rate_live
            store.push_sample("device", ip, rx_rate, tx_rate)
            devices_msg.append({
                "ip": ip, "rx_rate": round(rx_rate, 1), "tx_rate": round(tx_rate, 1),
                "conn_count": sessions_by_ip.get(ip, 0),
                "total_bytes": o_total + r_total,
            })
        self._prev_conns = {c.id: (now, c.orig_bytes, c.reply_bytes) for c in conns}
        self._prev_ip = {ip: (now, o, r) for ip, (o, r) in cur.items()}

        self.latest_session_rates = session_rates
        self.connected = True
        self.last_sample_ts = now

        await hub.publish("wan", {"interfaces": wan_data,
                                  "total": {"rx": total_rx, "tx": total_tx}})
        # CPU / 内存采样（与流量同周期）
        try:
            res = await self.client.get_system_resource()
            mem_used = res.total_memory - res.free_memory
            mem_pct = (mem_used / res.total_memory * 100) if res.total_memory else 0
            store.push_sample("sys", "cpu", res.cpu_load, 0)
            store.push_sample("sys", "mem", mem_pct, 0)
            await hub.publish("sys", {"cpu": res.cpu_load, "mem": mem_pct,
                                                        "mem_used": mem_used, "mem_total": res.total_memory,
                                                        "disk_free": res.disk_free, "disk_total": res.disk_total,
                                                        "conn_count": len(conns),
                                      "mem_used": mem_used, "mem_total": res.total_memory})
        except Exception:
            logger.warning("系统采样失败", exc_info=True)

        await hub.publish("devices", {"devices": devices_msg, "ts": now, "connected": True})

    async def _scan_new_devices(self) -> None:
        try:
            from app.services.devices import DeviceService
            devices = await DeviceService(self.client).list_devices()
            async with AsyncSessionLocal() as db:
                from app.services.alerts import scan_for_new_devices
                await scan_for_new_devices(db, devices)
        except Exception:
            logger.warning("新设备扫描失败", exc_info=True)

    async def _minute_loop(self) -> None:
        while self.running:
            try:
                await self._scan_new_devices()
            except Exception:
                pass
            await asyncio.sleep(60)
            try:
                await store.flush_minutely()
            except Exception:
                logger.exception("分钟聚合写入失败")
            if time.time() % 3600 < 60:
                try:
                    await store.cleanup()
                except Exception:
                    logger.exception("历史清理失败")















