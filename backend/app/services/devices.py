from __future__ import annotations
from pydantic import BaseModel
from app.adapters.ros.base import RouterOsClient


class DeviceView(BaseModel):
    ip: str
    mac: str = ""
    hostname: str = ""
    note: str = ""
    online: bool = False
    conn_count: int = 0
    blocked: bool = False
    rx_rate: float = 0.0
    tx_rate: float = 0.0
    total_bytes: int = 0
    iface: str = ""
    last_seen: str = ""
    expires_after: str = ""
    comment: str = ""


# 只把这些网段视为局域网终端；排除 198.18/15(fake-ip)、100.64/10(CGNAT)、10.40.x(上游 WAN 侧)
LAN_PREFIXES = ("192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
                "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")
WAN_SIDE_PREFIXES = ("198.18.", "198.19.", "100.64.", "100.65.", "100.66.", "100.67.",
                     "100.68.", "100.69.", "100.70.", "100.71.", "100.72.", "100.73.",
                     "100.74.", "100.75.", "100.76.", "100.77.", "100.78.", "100.79.",
                     "100.80.", "100.81.", "100.82.", "100.83.", "100.84.", "100.85.",
                     "100.86.", "100.87.", "100.88.", "100.89.", "100.90.", "100.91.",
                     "100.92.", "100.93.", "100.94.", "100.95.", "100.96.", "100.97.",
                     "100.98.", "100.99.", "100.100.", "100.101.", "100.102.", "100.103.",
                     "100.104.", "100.105.", "100.106.", "100.107.", "100.108.", "100.109.",
                     "100.110.", "100.111.", "100.112.", "100.113.", "100.114.", "100.115.",
                     "100.116.", "100.117.", "100.118.", "100.119.", "100.120.", "100.121.",
                     "100.122.", "100.123.", "100.124.", "100.125.", "100.126.", "100.127.")


def _private_ip(ip: str) -> bool:
    """是否为局域网终端地址（排除 WAN 侧与 fake-ip/保留段）。"""
    if not ip or ip == "255.255.255.255":
        return False
    if ip.startswith(WAN_SIDE_PREFIXES) or ip.startswith("10."):
        return False
    return ip.startswith(LAN_PREFIXES)


async def _gather(client: RouterOsClient):
    import asyncio

    async def safe(coro):
        try:
            return await coro
        except Exception:
            return []

    leases, arps, conns, blocked = await asyncio.gather(
        safe(client.list_leases()),
        safe(client.list_arp()),
        safe(client.list_connections()),
        safe(client.list_blocked()),
    )
    return leases, arps, conns, blocked


class DeviceService:
    def __init__(self, client: RouterOsClient):
        self.client = client

    async def list_devices(self) -> list[DeviceView]:
        leases, arps, conns, blocked = await _gather(self.client)
        devices: dict[str, DeviceView] = {}

        for lease in leases:
            if not lease.address or not _private_ip(lease.address):
                continue
            d = devices.setdefault(lease.address, DeviceView(ip=lease.address))
            d.mac = d.mac or lease.mac_address
            d.hostname = d.hostname or lease.host_name
            d.comment = getattr(lease, "comment", "") or ""
            if lease.status == "bound":
                d.online = True
            # DHCP last-seen / expires-after（适配器扩展字段，缺失时留空）
            d.last_seen = getattr(lease, "last_seen", "") or d.last_seen
            d.expires_after = getattr(lease, "expires_after", "") or d.expires_after
            d.expires_after = getattr(lease, "expires_after", "") or d.expires_after

        for arp in arps:
            if not arp.address or not _private_ip(arp.address):
                continue
            d = devices.setdefault(arp.address, DeviceView(ip=arp.address))
            d.mac = d.mac or arp.mac_address
            d.iface = d.iface or arp.interface

        now_ip_conns: dict[str, int] = {}
        bytes_by_ip: dict[str, int] = {}
        for c in conns:
            local_ip = c.src_ip if _private_ip(c.src_ip) else (
                c.dst_ip if _private_ip(c.dst_ip) else None)
            if local_ip is None:
                continue
            now_ip_conns[local_ip] = now_ip_conns.get(local_ip, 0) + 1
            bytes_by_ip[local_ip] = bytes_by_ip.get(local_ip, 0) + c.total_bytes
            if local_ip in devices:
                devices[local_ip].online = True

        blocked_set = set(blocked)
        for d in devices.values():
            d.conn_count = now_ip_conns.get(d.ip, 0)
            d.total_bytes = bytes_by_ip.get(d.ip, 0)
            d.blocked = d.ip in blocked_set

        return sorted(devices.values(), key=lambda d: ip_to_num(d.ip))


def ip_to_num(ip: str) -> int:
    parts = ip.split(".")
    if len(parts) != 4:
        return 0
    try:
        return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])
    except ValueError:
        return 0






