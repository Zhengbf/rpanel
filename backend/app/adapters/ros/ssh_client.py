from __future__ import annotations
import asyncio
import logging
import re
import asyncssh
from app.adapters.ros.base import (
    ConnectionTestResult, SystemResource, InterfaceInfo,
    TrafficSample, ConnectionEntry, ArpEntry, DhcpLease, FirewallState,
    DhcpServer, DhcpNetwork, IpPool, PortForward,
)
from app.adapters.ros.parser import (
    parse_detail_blocks, parse_bytes_value, parse_human_size, parse_percent,
    to_connection_entry,
)

logger = logging.getLogger(__name__)

_SAFE_IFACE = re.compile(r"^[a-zA-Z0-9_.\-]+$")
_SAFE_IP = re.compile(r"^[0-9a-fA-F.:]+$")
_SAFE_ID = re.compile(r"^\*?[0-9a-fA-F]+$")          # 租约 .id，如 *A1
_SAFE_MAC = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_.\-]+$")      # 服务器/连接名

_CMD_RESOURCE = "/system/resource/print"
_CMD_IDENTITY = "/system/identity/print"
_CMD_INTERFACES = "/interface/print detail"
_CMD_CONNECTIONS = "/ip/firewall/connection/print detail"
_CMD_ARP = "/ip/arp/print detail"
_CMD_LEASES = "/ip/dhcp-server/lease/print detail"
_CMD_FILTER_DETAIL = "/ip/firewall/filter/print detail"
_CMD_ADDR_LIST_TPL = "/ip/firewall/address-list/print detail where list={list_name}"


class SshRouterOsClient:
    BLOCKED_LIST_NAME = "router_panel_blocked"
    MANAGED_TAG = "managed-by=router-panel"

    def __init__(self, host: str, port: int = 22, username: str = "",
                 password: str = "", timeout: float = 10.0):
        self.host = host
        self.port = port
        self._auth = (username, password)
        self._timeout = timeout
        self._conn: asyncssh.SSHClientConnection | None = None

    async def _get_conn(self) -> asyncssh.SSHClientConnection:
        if self._conn is None or self._conn.is_closed():
            self._conn = await asyncssh.connect(
                self.host, port=self.port, username=self._auth[0],
                password=self._auth[1], known_hosts=None,
                connect_timeout=self._timeout)
        return self._conn

    async def _run(self, command: str) -> str:
        conn = await self._get_conn()
        result = await asyncio.wait_for(conn.run(command, check=True), timeout=self._timeout)
        return result.stdout or ""

    async def test_connection(self) -> ConnectionTestResult:
        try:
            out = await self._run(_CMD_RESOURCE)
            entries = parse_detail_blocks(out)
        except asyncssh.PermissionDenied:
            return ConnectionTestResult(ok=False, message="SSH 认证失败：用户名或密码错误")
        except asyncssh.DisconnectError as e:
            return ConnectionTestResult(ok=False, message=f"SSH 连接被断开：{e.code}")
        except (OSError, asyncio.TimeoutError) as e:
            from app.adapters.ros.rest_client import describe_connect_error
            detail = describe_connect_error(e)
            logger.warning("SSH 测试连接失败：%s:%s -> %s", self.host, self.port, detail,
                           exc_info=True)
            return ConnectionTestResult(ok=False, message=f"连不上路由器（SSH）：{detail}")
        except Exception as e:
            return ConnectionTestResult(ok=False, message=f"SSH 连接失败：{type(e).__name__}")
        if not entries:
            return ConnectionTestResult(ok=False, message="SSH 已连接但输出解析失败")
        res = entries[0]
        identity = ""
        try:
            out_id = await self._run(_CMD_IDENTITY)
            id_entries = parse_detail_blocks(out_id)
            if id_entries:
                identity = id_entries[0].get("name", "")
        except Exception:
            pass
        can_write = False
        try:
            await self._run(_CMD_FILTER_DETAIL)
            can_write = True
        except Exception:
            pass
        return ConnectionTestResult(
            ok=True, message="连接成功（SSH 模式，建议启用 REST）",
            routeros_version=res.get("version", "").split(" ")[0],
            identity=identity, can_read=True, can_write=can_write)

    async def get_system_resource(self) -> SystemResource:
        out = await self._run(_CMD_RESOURCE)
        entries = parse_detail_blocks(out)
        if not entries:
            return SystemResource()
        raw = entries[0]
        return SystemResource(
            version=raw.get("version", "").split(" ")[0],
            cpu_load=parse_percent(raw.get("cpu-load")),
            free_memory=parse_human_size(raw.get("free-memory")),
            total_memory=parse_human_size(raw.get("total-memory")),
            uptime=raw.get("uptime", ""),
        )

    async def get_identity(self) -> str:
        out = await self._run(_CMD_IDENTITY)
        entries = parse_detail_blocks(out)
        return entries[0].get("name", "") if entries else ""

    async def list_interfaces(self) -> list[InterfaceInfo]:
        out = await self._run(_CMD_INTERFACES)
        entries = parse_detail_blocks(out)
        result = []
        for raw in entries:
            flags = raw.get("_flags", "")
            result.append(InterfaceInfo(id=raw.get(".id", raw.get("id", "")),
                                        name=raw.get("name", ""), type=raw.get("type", ""),
                                        running="R" in flags, disabled="X" in flags))
        return result

    async def get_interface_counters(self) -> dict[str, dict[str, int]]:
        out = await self._run(_CMD_INTERFACES)
        result: dict[str, dict[str, int]] = {}
        for raw in parse_detail_blocks(out):
            name = raw.get("name", "")
            if not name:
                continue
            try:
                result[name] = {
                    "rx": int(float(raw.get("rx-byte", 0) or 0)),
                    "tx": int(float(raw.get("tx-byte", 0) or 0)),
                }
            except (TypeError, ValueError):
                result[name] = {"rx": 0, "tx": 0}
        return result

    async def monitor_traffic(self, iface: str):
        if not _SAFE_IFACE.match(iface):
            raise ValueError(f"非法接口名: {iface!r}")
        out = await self._run(f"/interface/monitor-traffic {iface} once")
        entries = parse_detail_blocks(out)
        for raw in entries:
            yield TrafficSample(
                interface=iface,
                rx_bits_per_second=float(raw.get("rx-bits-per-second", 0) or 0),
                tx_bits_per_second=float(raw.get("tx-bits-per-second", 0) or 0),
                rx_packets=float(raw.get("rx-packets", 0) or 0),
                tx_packets=float(raw.get("tx-packets", 0) or 0))

    async def list_connections(self) -> list[ConnectionEntry]:
        out = await self._run(_CMD_CONNECTIONS)
        entries = parse_detail_blocks(out)
        result = []
        for raw in entries:
            raw.setdefault(".id", raw.get("id", ""))
            entry = to_connection_entry(raw)
            result.append(entry)
        return result

    async def list_arp(self) -> list[ArpEntry]:
        out = await self._run(_CMD_ARP)
        entries = parse_detail_blocks(out)
        return [ArpEntry(id=raw.get(".id", raw.get("id", "")),
                         address=raw.get("address", ""),
                         mac_address=raw.get("mac-address", ""),
                         interface=raw.get("interface", ""),
                         complete=raw.get("status", "") == "complete" or "C" in raw.get("_flags", ""))
                for raw in entries]

    async def list_leases(self) -> list[DhcpLease]:
        out = await self._run(_CMD_LEASES)
        entries = parse_detail_blocks(out)
        return [DhcpLease(id=raw.get(".id", raw.get("id", "")),
                          address=raw.get("address", ""),
                          mac_address=raw.get("mac-address", ""),
                          host_name=raw.get("host-name", raw.get("hostname", "")),
                          server=raw.get("server", ""),
                          status=raw.get("status", ""),
                          active="A" in raw.get("_flags", "") or raw.get("status") == "bound")
                for raw in entries]

    async def get_ip_addresses(self) -> list[dict]:
        out = await self._run("/ip/address/print detail")
        return [{"interface": e.get("interface", ""), "address": e.get("address", ""),
                 "network": e.get("network", ""), "comment": e.get("comment", ""),
                 "dynamic": False, "disabled": False}
                for e in parse_detail_blocks(out)]

    async def export_config(self, sensitive: bool = False) -> str:
        """SSH 模式下 /export 直接返回脚本文本，同样不落文件。"""
        cmd = "/export"
        if sensitive:
            cmd += " show-sensitive"
        return await self._run(cmd)

    async def list_dhcp_servers(self) -> list[DhcpServer]:
        out = await self._run("/ip/dhcp-server/print detail")
        return [DhcpServer(
            id=e.get(".id", ""), name=e.get("name", ""), interface=e.get("interface", ""),
            address_pool=e.get("address-pool", ""), lease_time=e.get("lease-time", ""),
            disabled="X" in e.get("_flags", ""),
        ) for e in parse_detail_blocks(out)]

    async def list_dhcp_networks(self) -> list[DhcpNetwork]:
        out = await self._run("/ip/dhcp-server/network/print detail")
        return [DhcpNetwork(
            id=e.get(".id", ""), address=e.get("address", ""), gateway=e.get("gateway", ""),
            netmask=e.get("netmask", ""), dns_server=e.get("dns-server", ""),
            domain=e.get("domain", ""), comment=e.get("comment", ""),
        ) for e in parse_detail_blocks(out)]

    async def make_lease_static(self, lease_id: str) -> None:
        if not _SAFE_ID.match(lease_id):
            raise ValueError(f"非法租约 ID: {lease_id!r}")
        await self._run(f"/ip/dhcp-server/lease/make-static {lease_id}")

    async def add_static_lease(self, address: str, mac_address: str, server: str = "",
                               comment: str = "", host_name: str = "") -> None:
        if not _SAFE_IP.match(address):
            raise ValueError(f"非法地址: {address!r}")
        if not _SAFE_MAC.match(mac_address):
            raise ValueError(f"非法 MAC: {mac_address!r}")
        if server and not _SAFE_NAME.match(server):
            raise ValueError(f"非法 DHCP 服务器名: {server!r}")
        parts = [f"address={address}", f"mac-address={mac_address}", "disabled=no"]
        if server:
            parts.append(f"server={server}")
        note = comment or host_name
        if note:
            safe = note.replace('"', "")
            parts.append(f'comment="{safe}"')
        await self._run("/ip/dhcp-server/lease/add " + " ".join(parts))

    async def remove_lease(self, lease_id: str) -> None:
        if not _SAFE_ID.match(lease_id):
            raise ValueError(f"非法租约 ID: {lease_id!r}")
        await self._run(f"/ip/dhcp-server/lease/remove {lease_id}")

    async def set_lease(self, lease_id: str, fields: dict) -> None:
        if not _SAFE_ID.match(lease_id):
            raise ValueError(f"非法租约 ID: {lease_id!r}")
        parts = []
        if fields.get("address"):
            if not _SAFE_IP.match(str(fields["address"])):
                raise ValueError(f"非法地址: {fields['address']!r}")
            parts.append(f"address={fields['address']}")
        if fields.get("comment") is not None:
            safe = str(fields["comment"]).replace('"', "")
            parts.append(f'comment="{safe}"')
        if not parts:
            return
        await self._run(f"/ip/dhcp-server/lease/set {lease_id} " + " ".join(parts))

    async def add_dhcp_network(self, address: str, gateway: str = "", netmask: str = "",
                               dns_server: str = "", domain: str = "", comment: str = "") -> None:
        if not re.match(r"^[0-9./]+$", address):
            raise ValueError(f"非法网段: {address!r}")
        parts = [f"address={address}"]
        if gateway and _SAFE_IP.match(gateway):
            parts.append(f"gateway={gateway}")
        if netmask and _SAFE_IP.match(netmask):
            parts.append(f"netmask={netmask}")
        if dns_server:
            safe = dns_server.replace(",", ",").strip()
            if re.match(r"^[0-9., ]+$", safe):
                parts.append(f'dns-server="{safe}"')
        if domain and _SAFE_NAME.match(domain):
            parts.append(f"domain={domain}")
        if comment:
            parts.append(f'comment="{comment.replace(chr(34), "")}"')
        await self._run("/ip/dhcp-server/network/add " + " ".join(parts))

    async def set_dhcp_network(self, network_id: str, fields: dict) -> None:
        if not _SAFE_ID.match(network_id):
            raise ValueError(f"非法网段 ID: {network_id!r}")
        parts = []
        if fields.get("address"):
            parts.append(f"address={fields['address']}")
        if fields.get("gateway"):
            parts.append(f"gateway={fields['gateway']}")
        if fields.get("netmask"):
            parts.append(f"netmask={fields['netmask']}")
        if fields.get("dns_server"):
            parts.append(f'dns-server="{fields["dns_server"]}"')
        if fields.get("domain"):
            parts.append(f"domain={fields['domain']}")
        if fields.get("comment") is not None:
            parts.append(f'comment="{str(fields["comment"]).replace(chr(34), "")}"')
        if not parts:
            return
        await self._run(f"/ip/dhcp-server/network/set {network_id} " + " ".join(parts))

    async def remove_dhcp_network(self, network_id: str) -> None:
        if not _SAFE_ID.match(network_id):
            raise ValueError(f"非法网段 ID: {network_id!r}")
        await self._run(f"/ip/dhcp-server/network/remove {network_id}")

    async def list_ip_pools(self) -> list[IpPool]:
        out = await self._run("/ip/pool/print detail")
        return [IpPool(id=e.get(".id", ""), name=e.get("name", ""),
                       ranges=e.get("ranges", ""), comment=e.get("comment", ""))
                for e in parse_detail_blocks(out)]

    async def add_ip_pool(self, name: str, ranges: str, comment: str = "") -> None:
        if not _SAFE_NAME.match(name):
            raise ValueError(f"非法地址池名: {name!r}")
        if not re.match(r"^[0-9.\-,\s]+$", ranges):
            raise ValueError(f"非法地址范围: {ranges!r}")
        cmd = f'/ip/pool/add name={name} ranges="{ranges}"'
        if comment:
            cmd += f' comment="{comment.replace(chr(34), "")}"'
        await self._run(cmd)

    async def set_ip_pool(self, pool_id: str, fields: dict) -> None:
        if not _SAFE_ID.match(pool_id):
            raise ValueError(f"非法地址池 ID: {pool_id!r}")
        parts = []
        if fields.get("name"):
            parts.append(f"name={fields['name']}")
        if fields.get("ranges"):
            parts.append(f'ranges="{fields["ranges"]}"')
        if fields.get("comment") is not None:
            parts.append(f'comment="{str(fields["comment"]).replace(chr(34), "")}"')
        if parts:
            await self._run(f"/ip/pool/set {pool_id} " + " ".join(parts))

    async def remove_ip_pool(self, pool_id: str) -> None:
        if not _SAFE_ID.match(pool_id):
            raise ValueError(f"非法地址池 ID: {pool_id!r}")
        await self._run(f"/ip/pool/remove {pool_id}")

    async def add_dhcp_server(self, name: str, interface: str, address_pool: str = "",
                              lease_time: str = "1d") -> None:
        for label, value in (("服务器名", name), ("接口", interface)):
            if not _SAFE_NAME.match(value):
                raise ValueError(f"非法{label}: {value!r}")
        parts = [f"name={name}", f"interface={interface}", "disabled=no"]
        if address_pool:
            if not _SAFE_NAME.match(address_pool):
                raise ValueError(f"非法地址池名: {address_pool!r}")
            parts.append(f"address-pool={address_pool}")
        if lease_time and re.match(r"^[0-9a-zA-Z:.]+$", lease_time):
            parts.append(f"lease-time={lease_time}")
        await self._run("/ip/dhcp-server/add " + " ".join(parts))

    async def set_dhcp_server(self, server_id: str, fields: dict) -> None:
        if not _SAFE_ID.match(server_id):
            raise ValueError(f"非法服务器 ID: {server_id!r}")
        parts = []
        for key, target in (("name", "name"), ("interface", "interface"),
                            ("address_pool", "address-pool"), ("lease_time", "lease-time")):
            value = fields.get(key)
            if value:
                if not _SAFE_NAME.match(str(value)):
                    raise ValueError(f"非法值 {key}={value!r}")
                parts.append(f"{target}={value}")
        if fields.get("disabled") is not None:
            parts.append("disabled=" + ("yes" if fields["disabled"] else "no"))
        if not parts:
            return
        await self._run(f"/ip/dhcp-server/set {server_id} " + " ".join(parts))

    async def remove_dhcp_server(self, server_id: str) -> None:
        if not _SAFE_ID.match(server_id):
            raise ValueError(f"非法服务器 ID: {server_id!r}")
        await self._run(f"/ip/dhcp-server/remove {server_id}")

    # --- 防火墙 filter 规则（一键放通场景使用）---

    async def list_filter_rules(self) -> list[dict]:
        out = await self._run(_CMD_FILTER_DETAIL)
        return parse_detail_blocks(out)

    async def add_filter_rule(self, fields: dict, place_before: str | None = None) -> dict:
        parts: list[str] = []
        for key, value in fields.items():
            if value in (None, ""):
                continue
            if key not in ("chain", "action", "protocol", "dst-port", "in-interface",
                           "in-interface-list", "src-address", "comment"):
                raise ValueError(f"不允许的规则字段: {key}")
            text = str(value)
            if any(ch in text for ch in ('"', "\\", "\n", "\r")):
                raise ValueError(f"字段 {key} 含非法字符")
            parts.append(f'{key}="{text}"')
        if place_before:
            if not _SAFE_ID.match(place_before):
                raise ValueError(f"非法规则 ID: {place_before!r}")
            parts.append(f"place-before={place_before}")
        await self._run("/ip/firewall/filter/add " + " ".join(parts))
        return {}

    async def remove_filter_rule(self, rule_id: str) -> None:
        if not _SAFE_ID.match(rule_id):
            raise ValueError(f"非法规则 ID: {rule_id!r}")
        await self._run(f"/ip/firewall/filter/remove {rule_id}")

    async def list_interface_list_members(self) -> list[dict]:
        out = await self._run("/interface/list/member/print detail")
        return parse_detail_blocks(out)

    async def _ensure_drop_rule(self, wan_interfaces: list[str] | None = None) -> None:
        """按 WAN 口逐口创建 drop 规则。幂等。"""
        out = await self._run(_CMD_FILTER_DETAIL)
        entries = parse_detail_blocks(out)
        managed_out = set()
        for raw in entries:
            if raw.get("chain") == "forward" and raw.get("comment") == self.MANAGED_TAG:
                managed_out.add(raw.get("out-interface", ""))
        import re as _re
        for iface in (wan_interfaces or []):
            if not _re.match(r"^[a-zA-Z0-9_.\-]+$", iface):
                continue
            if iface in managed_out:
                continue
            await self._run(
                "/ip/firewall/filter/add chain=forward action=drop "
                f"src-address-list={self.BLOCKED_LIST_NAME} "
                f"out-interface={iface} "
                f'comment="{self.MANAGED_TAG}" place-before=0')

    async def _maybe_remove_drop_rule(self) -> None:
        list_out = await self._run(_CMD_ADDR_LIST_TPL.format(list_name=self.BLOCKED_LIST_NAME))
        if parse_detail_blocks(list_out):
            return
        out = await self._run(_CMD_FILTER_DETAIL)
        for raw in parse_detail_blocks(out):
            if raw.get("chain") == "forward" and raw.get("comment") == self.MANAGED_TAG:
                rid = raw.get(".id", "")
                if rid:
                    await self._run(f"/ip/firewall/filter/remove {rid}")

    async def add_block(self, ip: str, wan_interfaces: list[str]) -> None:
        if not _SAFE_IP.match(ip):
            raise ValueError(f"非法 IP: {ip!r}")
        list_out = await self._run(_CMD_ADDR_LIST_TPL.format(list_name=self.BLOCKED_LIST_NAME))
        entries = parse_detail_blocks(list_out)
        already = any(e.get("address") == ip for e in entries)
        if not already:
            await self._run(
                f"/ip/firewall/address-list/add list={self.BLOCKED_LIST_NAME} "
                f"address={ip} comment=\"{self.MANAGED_TAG}\"")
        await self._ensure_drop_rule(wan_interfaces)

    async def remove_block(self, ip: str, wan_interfaces: list[str]) -> None:
        if not _SAFE_IP.match(ip):
            raise ValueError(f"非法 IP: {ip!r}")
        list_out = await self._run(_CMD_ADDR_LIST_TPL.format(list_name=self.BLOCKED_LIST_NAME))
        entries = parse_detail_blocks(list_out)
        for raw in entries:
            if raw.get("address") == ip:
                rid = raw.get(".id", "")
                if rid:
                    await self._run(f"/ip/firewall/address-list/remove {rid}")
        await self._maybe_remove_drop_rule()

    async def list_blocked(self) -> list[str]:
        out = await self._run(_CMD_ADDR_LIST_TPL.format(list_name=self.BLOCKED_LIST_NAME))
        return [e.get("address", "") for e in parse_detail_blocks(out) if e.get("address")]

    async def get_firewall_state(self) -> FirewallState:
        blocked = await self.list_blocked()
        out = await self._run(_CMD_FILTER_DETAIL)
        managed, other = [], 0
        for raw in parse_detail_blocks(out):
            if raw.get("chain") != "forward":
                continue
            if raw.get("comment") == self.MANAGED_TAG:
                managed.append(raw)
            else:
                other += 1
        return FirewallState(blocked_ips=blocked, managed_rules=managed, other_rules_count=other)

    async def clear_connections(self, ip: str) -> None:
        if not _SAFE_IP.match(ip):
            raise ValueError(f"非法 IP: {ip!r}")
        out = await self._run(_CMD_CONNECTIONS)
        entries = parse_detail_blocks(out)
        for raw in entries:
            src = raw.get("src-address", "")
            dst = raw.get("dst-address", "")
            if ip in src or ip in dst:
                rid = raw.get(".id", "")
                if rid:
                    try:
                        await self._run(f"/ip/firewall/connection/remove {rid}")
                    except asyncssh.ProcessError:
                        pass

    async def list_port_forwards(self) -> list[PortForward]:
        out = await self._run("/ip/firewall/nat/print detail")
        result = []
        for raw in parse_detail_blocks(out):
            if raw.get("chain") != "dstnat" or raw.get("action") != "dst-nat":
                continue
            result.append(PortForward(
                id=raw.get(".id", ""), protocol=raw.get("protocol", ""),
                dst_address=raw.get("dst-address", ""), dst_port=raw.get("dst-port", ""),
                to_addresses=raw.get("to-addresses", ""), to_ports=raw.get("to-ports", ""),
                in_interface=raw.get("in-interface", ""), comment=raw.get("comment", ""),
                disabled="X" in raw.get("_flags", ""),
            ))
        return result

    async def add_port_forward(self, *, protocol: str, dst_port: str, to_addresses: str,
                               to_ports: str = "", in_interface: str = "", comment: str = "") -> None:
        if protocol not in ("tcp", "udp"):
            raise ValueError(f"非法协议: {protocol!r}")
        if not re.match(r"^[0-9,\-]+$", dst_port):
            raise ValueError(f"非法目标端口: {dst_port!r}")
        if not _SAFE_IP.match(to_addresses):
            raise ValueError(f"非法内部地址: {to_addresses!r}")
        if to_ports and not re.match(r"^[0-9,\-]+$", to_ports):
            raise ValueError(f"非法映射端口: {to_ports!r}")
        parts = ["chain=dstnat", "action=dst-nat", f"protocol={protocol}",
                 f"dst-port={dst_port}", f"to-addresses={to_addresses}"]
        if to_ports:
            parts.append(f"to-ports={to_ports}")
        if in_interface:
            if not _SAFE_IFACE.match(in_interface):
                raise ValueError(f"非法接口: {in_interface!r}")
            parts.append(f"in-interface={in_interface}")
        if comment:
            parts.append(f'comment="{comment.replace(chr(34), "")}"')
        await self._run("/ip/firewall/nat/add " + " ".join(parts))

    async def set_port_forward(self, rule_id: str, fields: dict) -> None:
        if not _SAFE_ID.match(rule_id):
            raise ValueError(f"非法规则 ID: {rule_id!r}")
        parts: list[str] = []
        if fields.get("protocol"):
            if fields["protocol"] not in ("tcp", "udp"):
                raise ValueError(f"非法协议: {fields['protocol']!r}")
            parts.append(f"protocol={fields['protocol']}")
        if fields.get("dst_port"):
            if not re.match(r"^[0-9,\-]+$", str(fields["dst_port"])):
                raise ValueError(f"非法目标端口: {fields['dst_port']!r}")
            parts.append(f"dst-port={fields['dst_port']}")
        if fields.get("to_addresses"):
            if not _SAFE_IP.match(str(fields["to_addresses"])):
                raise ValueError(f"非法内部地址: {fields['to_addresses']!r}")
            parts.append(f"to-addresses={fields['to_addresses']}")
        if fields.get("to_ports"):
            if not re.match(r"^[0-9,\-]+$", str(fields["to_ports"])):
                raise ValueError(f"非法映射端口: {fields['to_ports']!r}")
            parts.append(f"to-ports={fields['to_ports']}")
        if fields.get("in_interface"):
            if not _SAFE_IFACE.match(str(fields["in_interface"])):
                raise ValueError(f"非法接口: {fields['in_interface']!r}")
            parts.append(f"in-interface={fields['in_interface']}")
        if fields.get("comment") is not None:
            parts.append(f'comment="{str(fields["comment"]).replace(chr(34), "")}"')
        if fields.get("disabled") is not None:
            parts.append("disabled=" + ("yes" if fields["disabled"] else "no"))
        if parts:
            await self._run(f"/ip/firewall/nat/set {rule_id} " + " ".join(parts))

    async def remove_port_forward(self, rule_id: str) -> None:
        if not _SAFE_ID.match(rule_id):
            raise ValueError(f"非法规则 ID: {rule_id!r}")
        await self._run(f"/ip/firewall/nat/remove {rule_id}")

    async def close(self) -> None:
        if self._conn and not self._conn.is_closed():
            self._conn.close()
            await self._conn.wait_closed()


