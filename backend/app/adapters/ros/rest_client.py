"""
RouterOS 7 REST API 适配器。
"""
from __future__ import annotations
import asyncio
import json
import logging
import httpx
from app.adapters.ros.base import (
    ConnectionTestResult, SystemResource, InterfaceInfo,
    TrafficSample, ConnectionEntry, ArpEntry, DhcpLease, FirewallState,
    DhcpServer, DhcpNetwork, IpPool, PortForward,
)
from app.adapters.ros.parser import to_connection_entry

logger = logging.getLogger(__name__)


def describe_connect_error(exc: BaseException) -> str:
    """把底层连接异常翻译成能直接定位问题的一句话。

    以前这里只回“无法连接到路由器，请检查 IP/端口/HTTPS”，
    无论是主机不可达、超时、端口没服务还是 TLS 握手失败都长得一样，
    排查时只能靠猜。现在把 errno / 底层类型还原出来。
    """
    cause = exc.__cause__ or exc
    errno_value = getattr(cause, "errno", None)
    text = f"{type(cause).__name__}: {cause}"
    low = text.lower()

    if "wrong version number" in low or "record layer" in low or "ssl" in low \
            or "certificate" in low:
        return "TLS 握手失败：该端口不是 HTTPS 服务（REST 要用 443，SSH 要用 22）"
    if errno_value in (101, 113) or "unreachable" in low or "no route" in low:
        return "主机不可达（no route to host）：这台机器到路由器的网络不通"
    if errno_value == 111 or "refused" in low:
        return "连接被拒绝：端口上没有服务在监听"
    if errno_value == 110 or "timed out" in low or "timeout" in low:
        return "连接超时：目标没有响应（可能被防火墙丢弃）"
    if "name or service not known" in low or "nodename" in low or "getaddrinfo" in low:
        return "主机名解析失败：请直接填路由器 IP"
    return text


class RestRouterOsClient:
    BLOCKED_LIST_NAME = "router_panel_blocked"
    MANAGED_TAG = "managed-by=router-panel"

    def __init__(self, host: str, port: int = 443, username: str = "",
                 password: str = "", verify_tls: bool = False, timeout: float = 10.0):
        self.base_url = f"https://{host}:{port}/rest"
        self._auth = (username, password)
        self._verify = verify_tls
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # trust_env=False：不读宿主机的 HTTP(S)_PROXY。
            # 容器里被塞进代理变量时，内网地址会被错误地丢给代理，直接连不上路由器。
            self._client = httpx.AsyncClient(base_url=self.base_url, auth=self._auth,
                                             verify=self._verify, timeout=self._timeout,
                                             trust_env=False)
        return self._client

    async def _get(self, path: str) -> list | dict:
        client = await self._get_client()
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict | None = None) -> list | dict:
        client = await self._get_client()
        resp = await client.post(path, json=body or {})
        resp.raise_for_status()
        return resp.json()

    async def _put(self, path: str, body: dict) -> dict:
        # RouterOS 7 的 REST 用 PUT 新增条目，POST 只用于执行命令
        client = await self._get_client()
        resp = await client.put(path, json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def _delete(self, path: str) -> None:
        client = await self._get_client()
        resp = await client.delete(path)
        resp.raise_for_status()


    async def test_connection(self) -> ConnectionTestResult:
        try:
            res = await self.get_system_resource()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (401, 403):
                return ConnectionTestResult(ok=False, message="认证失败：用户名或密码错误，或权限不足")
            return ConnectionTestResult(ok=False, message=f"HTTP 错误 {code}")
        except httpx.ConnectTimeout:
            logger.warning("测试连接超时：%s（%s 秒）", self.base_url, self._timeout)
            return ConnectionTestResult(
                ok=False, message="连接超时：路由器没有响应，检查端口是否可达（可能被防火墙丢弃）")
        except httpx.ConnectError as e:
            detail = describe_connect_error(e)
            logger.warning("测试连接失败：%s -> %s", self.base_url, detail, exc_info=True)
            return ConnectionTestResult(ok=False, message=f"连不上路由器：{detail}")
        except Exception as e:
            detail = describe_connect_error(e)
            logger.warning("测试连接异常：%s -> %s", self.base_url, detail, exc_info=True)
            return ConnectionTestResult(ok=False, message=f"连接失败：{detail}")
        try:
            identity_raw = await self._get("/system/identity")
            identity = identity_raw.get("name", "") if isinstance(identity_raw, dict) else ""
        except Exception:
            identity = ""
        can_write = False
        try:
            await self._get("/ip/firewall/address-list")
            can_write = True
        except Exception:
            pass
        return ConnectionTestResult(ok=True, message="连接成功",
                                    routeros_version=res.version, identity=identity,
                                    can_read=True, can_write=can_write)

    async def get_system_resource(self) -> SystemResource:
        raw = await self._get("/system/resource")
        if not isinstance(raw, dict):
            return SystemResource()
        return SystemResource(
            version=str(raw.get("version", "")).split(" ")[0],
            cpu_load=float(raw.get("cpu-load", 0) or 0),
            free_memory=int(raw.get("free-memory", 0) or 0),
            total_memory=int(raw.get("total-memory", 0) or 0),
            uptime=str(raw.get("uptime", "")),
            disk_free=int(raw.get("free-hdd-space", 0) or 0),
            disk_total=int(raw.get("total-hdd-space", 0) or 0),
            cpu_count=int(raw.get("cpu-count", 0) or 0),
        )

    async def get_identity(self) -> str:
        raw = await self._get("/system/identity")
        return raw.get("name", "") if isinstance(raw, dict) else ""

    async def list_interfaces(self) -> list[InterfaceInfo]:
        raw_list = await self._get("/interface")
        if not isinstance(raw_list, list):
            return []
        result = []
        for r in raw_list:
            if not isinstance(r, dict):
                continue
            result.append(InterfaceInfo(
                id=r.get(".id", ""),
                name=r.get("name", ""),
                type=r.get("type", ""),
                running=str(r.get("running", "false")).lower() == "true",
                disabled=str(r.get("disabled", "false")).lower() == "true",
            ))
        return result

    async def monitor_traffic(self, iface: str):
        """monitor-traffic：返回 JSON 数组（7.x 实测），SSE 格式兜底。"""
        client = await self._get_client()
        resp = await client.post("/interface/monitor-traffic",
                                 json={"interface": iface, "once": ""})
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        samples: list[TrafficSample] = []
        if "json" in ctype or resp.text.strip().startswith("["):
            try:
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        samples.append(TrafficSample(
                            interface=iface,
                            rx_bits_per_second=float(item.get("rx-bits-per-second", 0) or 0),
                            tx_bits_per_second=float(item.get("tx-bits-per-second", 0) or 0),
                            rx_packets=float(item.get("rx-packets-per-second", 0) or 0),
                            tx_packets=float(item.get("tx-packets-per-second", 0) or 0)))
            except Exception:
                pass
        if not samples:
            for line in resp.text.splitlines():
                if line.startswith("data:") or line.startswith("data: "):
                    payload = line[5:].strip()
                    try:
                        d = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    samples.append(TrafficSample(
                        interface=iface,
                        rx_bits_per_second=float(d.get("rx-bits-per-second", 0) or 0),
                        tx_bits_per_second=float(d.get("tx-bits-per-second", 0) or 0),
                        rx_packets=float(d.get("rx-packets-per-second", 0) or 0),
                        tx_packets=float(d.get("tx-packets-per-second", 0) or 0)))
        for s in samples:
            yield s

    async def list_connections(self) -> list[ConnectionEntry]:
        raw_list = await self._get("/ip/firewall/connection")
        if not isinstance(raw_list, list):
            return []
        return [to_connection_entry(r) for r in raw_list]

    async def list_arp(self) -> list[ArpEntry]:
        raw_list = await self._get("/ip/arp")
        if not isinstance(raw_list, list):
            return []
        return [ArpEntry(id=r.get(".id", ""), address=r.get("address", ""),
                         mac_address=r.get("mac-address", ""), interface=r.get("interface", ""),
                         complete=str(r.get("complete", "false")).lower() == "true")
                for r in raw_list]

    async def list_leases(self) -> list[DhcpLease]:
        raw_list = await self._get("/ip/dhcp-server/lease")
        if not isinstance(raw_list, list):
            return []
        return [DhcpLease(id=r.get(".id", ""), address=r.get("address", ""),
                          mac_address=r.get("mac-address", ""),
                          host_name=r.get("host-name", r.get("hostname", "")),
                          server=r.get("server", ""), status=r.get("status", ""),
                          active=str(r.get("active", "false")).lower() == "true",
                          last_seen=str(r.get("last-seen", r.get("last_seen", "")) or ""),
                          expires_after=str(r.get("expires-after", "") or ""),
                          comment=str(r.get("comment", "") or ""),
                          dynamic=str(r.get("dynamic", "false")).lower() == "true",
                          disabled=str(r.get("disabled", "false")).lower() == "true",
                          blocked=str(r.get("blocked", "false")).lower() == "true",
                          ) for r in raw_list]

    # ---------------- DHCP 管理 ----------------

    async def list_dhcp_servers(self) -> list[DhcpServer]:
        raw = await self._get("/ip/dhcp-server")
        if not isinstance(raw, list):
            return []
        return [DhcpServer(
            id=r.get(".id", ""),
            name=r.get("name", ""),
            interface=r.get("interface", ""),
            address_pool=r.get("address-pool", ""),
            lease_time=r.get("lease-time", ""),
            disabled=str(r.get("disabled", "false")).lower() == "true",
            dynamic=str(r.get("dynamic", "false")).lower() == "true",
        ) for r in raw]

    async def list_dhcp_networks(self) -> list[DhcpNetwork]:
        raw = await self._get("/ip/dhcp-server/network")
        if not isinstance(raw, list):
            return []
        return [DhcpNetwork(
            id=r.get(".id", ""),
            address=r.get("address", ""),
            gateway=r.get("gateway", ""),
            netmask=r.get("netmask", ""),
            dns_server=r.get("dns-server", ""),
            domain=r.get("domain", ""),
            comment=r.get("comment", ""),
        ) for r in raw]

    async def make_lease_static(self, lease_id: str) -> None:
        """把动态租约转为静态绑定（RouterOS 命令：make-static）。"""
        await self._post("/ip/dhcp-server/lease/make-static", {".id": lease_id})

    async def add_static_lease(self, address: str, mac_address: str, server: str = "",
                               comment: str = "", host_name: str = "") -> None:
        body: dict = {"address": address, "mac-address": mac_address, "disabled": "false"}
        if server:
            body["server"] = server
        if comment:
            body["comment"] = comment
        if host_name:
            body["comment"] = comment or host_name
        await self._post("/ip/dhcp-server/lease/add", body)

    async def remove_lease(self, lease_id: str) -> None:
        await self._post("/ip/dhcp-server/lease/remove", {".id": lease_id})

    async def set_lease(self, lease_id: str, fields: dict) -> None:
        body = {".id": lease_id}
        for key in ("address", "comment", "server"):
            if fields.get(key) is not None:
                body[key] = fields[key]
        if len(body) > 1:
            await self._post("/ip/dhcp-server/lease/set", body)

    async def add_dhcp_network(self, address: str, gateway: str = "", netmask: str = "",
                               dns_server: str = "", domain: str = "", comment: str = "") -> None:
        body: dict = {"address": address}
        for key, value in (("gateway", gateway), ("netmask", netmask),
                           ("dns-server", dns_server), ("domain", domain), ("comment", comment)):
            if value:
                body[key] = value
        await self._post("/ip/dhcp-server/network/add", body)

    async def set_dhcp_network(self, network_id: str, fields: dict) -> None:
        body = {".id": network_id}
        mapping = {"address": "address", "gateway": "gateway", "netmask": "netmask",
                   "dns_server": "dns-server", "domain": "domain", "comment": "comment"}
        for key, target in mapping.items():
            if key in fields and fields[key] is not None:
                body[target] = fields[key]
        await self._post("/ip/dhcp-server/network/set", body)

    async def remove_dhcp_network(self, network_id: str) -> None:
        await self._post("/ip/dhcp-server/network/remove", {".id": network_id})

    async def list_ip_pools(self) -> list[IpPool]:
        raw = await self._get("/ip/pool")
        if not isinstance(raw, list):
            return []
        return [IpPool(id=r.get(".id", ""), name=r.get("name", ""),
                       ranges=r.get("ranges", ""), comment=r.get("comment", ""))
                for r in raw]

    async def add_ip_pool(self, name: str, ranges: str, comment: str = "") -> None:
        body: dict = {"name": name, "ranges": ranges}
        if comment:
            body["comment"] = comment
        await self._post("/ip/pool/add", body)

    async def set_ip_pool(self, pool_id: str, fields: dict) -> None:
        body = {".id": pool_id}
        for key in ("name", "ranges", "comment"):
            if fields.get(key) is not None:
                body[key] = fields[key]
        await self._post("/ip/pool/set", body)

    async def remove_ip_pool(self, pool_id: str) -> None:
        await self._post("/ip/pool/remove", {".id": pool_id})

    async def add_dhcp_server(self, name: str, interface: str, address_pool: str = "",
                              lease_time: str = "1d") -> None:
        body: dict = {"name": name, "interface": interface, "disabled": "false"}
        if address_pool:
            body["address-pool"] = address_pool
        if lease_time:
            body["lease-time"] = lease_time
        await self._post("/ip/dhcp-server/add", body)

    async def set_dhcp_server(self, server_id: str, fields: dict) -> None:
        body = {".id": server_id}
        mapping = {"name": "name", "interface": "interface", "address_pool": "address-pool",
                   "lease_time": "lease-time", "disabled": "disabled"}
        for key, target in mapping.items():
            if key in fields and fields[key] is not None:
                value = fields[key]
                if key == "disabled":
                    value = "true" if value else "false"
                body[target] = value
        await self._post("/ip/dhcp-server/set", body)

    async def remove_dhcp_server(self, server_id: str) -> None:
        await self._post("/ip/dhcp-server/remove", {".id": server_id})

    async def export_config(self, sensitive: bool = False) -> str:
        """REST 拿不到 /export 的输出，这里直接拒绝并说明原因。

        实测（RouterOS 7.x）：POST /rest/export 恒返回空数组，不会把命令
        输出放进响应体；GET /rest/file/<name> 只回文件元数据，读不到内容。
        所以配置导出只能走 SSH，见 app/api/backup.py。
        """
        raise NotImplementedError(
            "RouterOS REST 无法读取 /export 输出，请使用 SSH 方式导出配置")

    async def get_ip_addresses(self) -> list[dict]:
        """IP 地址列表（含接口、掩码、comment、动态标记）。"""
        raw = await self._get("/ip/address")
        if not isinstance(raw, list):
            return []
        out = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            out.append({
                "interface": r.get("interface", ""),
                "address": r.get("address", ""),
                "network": r.get("network", ""),
                "comment": r.get("comment", ""),
                "dynamic": str(r.get("dynamic", "false")).lower() == "true",
                "disabled": str(r.get("disabled", "false")).lower() == "true",
            })
        return out

    async def get_interface_counters(self) -> dict[str, dict[str, int]]:
        """接口累计字节数。RouterOS 暴露的是 rx-byte / tx-byte，用于稳定差分。"""
        raw = await self._get("/interface")
        out: dict[str, dict[str, int]] = {}
        if isinstance(raw, list):
            for r in raw:
                if not isinstance(r, dict):
                    continue
                name = r.get("name", "")
                if not name:
                    continue
                try:
                    out[name] = {
                        "rx": int(float(r.get("rx-byte", 0) or 0)),
                        "tx": int(float(r.get("tx-byte", 0) or 0)),
                    }
                except (TypeError, ValueError):
                    out[name] = {"rx": 0, "tx": 0}
        return out

    # ---------------- 端口转发 ----------------

    async def list_port_forwards(self) -> list[PortForward]:
        raw = await self._get("/ip/firewall/nat")
        if not isinstance(raw, list):
            return []
        out = []
        for r in raw:
            if not isinstance(r, dict) or r.get("chain") != "dstnat" or r.get("action") != "dst-nat":
                continue
            out.append(PortForward(
                id=r.get(".id", ""),
                protocol=r.get("protocol", ""),
                dst_address=r.get("dst-address", ""),
                dst_port=r.get("dst-port", ""),
                to_addresses=r.get("to-addresses", ""),
                to_ports=r.get("to-ports", ""),
                in_interface=r.get("in-interface", ""),
                comment=r.get("comment", ""),
                disabled=str(r.get("disabled", "false")).lower() == "true",
            ))
        return out

    async def add_port_forward(self, *, protocol: str, dst_port: str, to_addresses: str,
                               to_ports: str = "", in_interface: str = "", comment: str = "") -> None:
        import ipaddress
        import re
        if protocol not in ("tcp", "udp"):
            raise ValueError(f"非法协议: {protocol!r}")
        if not re.fullmatch(r"[0-9,\-]+", dst_port):
            raise ValueError(f"非法目标端口: {dst_port!r}")
        try:
            ip = ipaddress.ip_address(to_addresses)
        except ValueError:
            raise ValueError(f"非法内部地址: {to_addresses!r}")
        if not ip.is_private:
            raise ValueError(f"只允许转发到私网地址: {to_addresses!r}")
        if to_ports and not re.fullmatch(r"[0-9,\-]+", to_ports):
            raise ValueError(f"非法映射端口: {to_ports!r}")
        if in_interface and not re.fullmatch(r"[a-zA-Z0-9_.\-]+", in_interface):
            raise ValueError(f"非法接口: {in_interface!r}")
        body: dict = {
            "chain": "dstnat", "action": "dst-nat",
            "protocol": protocol, "dst-port": dst_port,
            "to-addresses": to_addresses,
        }
        if to_ports:
            body["to-ports"] = to_ports
        if in_interface:
            body["in-interface"] = in_interface
        if comment:
            body["comment"] = comment
        await self._post("/ip/firewall/nat/add", body)

    async def set_port_forward(self, rule_id: str, fields: dict) -> None:
        body: dict = {".id": rule_id}
        mapping = {
            "protocol": "protocol", "dst_port": "dst-port",
            "to_addresses": "to-addresses", "to_ports": "to-ports",
            "in_interface": "in-interface", "comment": "comment",
        }
        for key, target in mapping.items():
            if fields.get(key) is not None:
                body[target] = fields[key]
        if "disabled" in fields:
            body["disabled"] = "true" if fields["disabled"] else "false"
        await self._post("/ip/firewall/nat/set", body)

    async def remove_port_forward(self, rule_id: str) -> None:
        await self._post("/ip/firewall/nat/remove", {".id": rule_id})

    async def _ensure_drop_rule(self, wan_interfaces: list[str] | None = None) -> None:
        """按 WAN 口逐口创建 drop 规则：封 WAN 出方向，不影响 LAN 互访。幂等。"""
        rules = await self._get("/ip/firewall/filter")
        if not isinstance(rules, list):
            rules = []
        forward_rules = [r for r in rules if r.get("chain") == "forward"]
        managed = [r for r in forward_rules if r.get("comment", "") == self.MANAGED_TAG]
        managed_out = {r.get("out-interface", "") for r in managed}
        place_before = None
        for r in forward_rules:
            if r.get("comment", "") == self.MANAGED_TAG:
                continue
            place_before = r.get(".id")
            break
        ifaces = wan_interfaces or []
        for iface in ifaces:
            if iface in managed_out:
                continue
            body: dict = {"chain": "forward", "action": "drop",
                          "src-address-list": self.BLOCKED_LIST_NAME,
                          "out-interface": iface,
                          "comment": self.MANAGED_TAG}
            if place_before:
                body["place-before"] = place_before
            await self._post("/ip/firewall/filter/add", body)

    async def _maybe_remove_drop_rule(self) -> None:
        entries = await self._get(f"/ip/firewall/address-list?list={self.BLOCKED_LIST_NAME}")
        if isinstance(entries, list) and entries:
            return
        rules = await self._get("/ip/firewall/filter")
        if isinstance(rules, list):
            for r in rules:
                if (r.get("comment", "") == self.MANAGED_TAG
                        and r.get("chain") == "forward"):
                    rid = r.get(".id")
                    if rid:
                        await self._post("/ip/firewall/filter/remove", {".id": rid})

    async def add_block(self, ip: str, wan_interfaces: list[str]) -> None:
        entries = await self._get(f"/ip/firewall/address-list?list={self.BLOCKED_LIST_NAME}&address={ip}")
        if isinstance(entries, list) and not entries:
            await self._post("/ip/firewall/address-list/add", {
                "list": self.BLOCKED_LIST_NAME, "address": ip, "comment": self.MANAGED_TAG})
        await self._ensure_drop_rule(wan_interfaces)

    async def remove_block(self, ip: str, wan_interfaces: list[str]) -> None:
        entries = await self._get(f"/ip/firewall/address-list?list={self.BLOCKED_LIST_NAME}&address={ip}")
        if isinstance(entries, list):
            for e in entries:
                rid = e.get(".id")
                if rid:
                    await self._post("/ip/firewall/address-list/remove", {".id": rid})
        await self._maybe_remove_drop_rule()

    async def list_blocked(self) -> list[str]:
        entries = await self._get(f"/ip/firewall/address-list?list={self.BLOCKED_LIST_NAME}")
        if not isinstance(entries, list):
            return []
        return [e.get("address", "") for e in entries if e.get("address")]

    async def get_firewall_state(self) -> FirewallState:
        entries = await self._get(f"/ip/firewall/address-list?list={self.BLOCKED_LIST_NAME}")
        blocked = [e.get("address", "") for e in entries if e.get("address")] if isinstance(entries, list) else []
        rules = await self._get("/ip/firewall/filter")
        managed, other = [], 0
        if isinstance(rules, list):
            for r in rules:
                if r.get("chain") != "forward":
                    continue
                if r.get("comment", "") == self.MANAGED_TAG:
                    managed.append(r)
                else:
                    other += 1
        return FirewallState(blocked_ips=blocked, managed_rules=managed, other_rules_count=other)

    async def clear_connections(self, ip: str) -> None:
        conns = await self._get("/ip/firewall/connection")
        if not isinstance(conns, list):
            return
        for c in conns:
            src = str(c.get("src-address", "")) + str(c.get("src-port", ""))
            dst = str(c.get("dst-address", "")) + str(c.get("dst-port", ""))
            if ip in src or ip in dst:
                rid = c.get(".id")
                if rid:
                    try:
                        await self._post("/ip/firewall/connection/remove", {".id": rid})
                    except httpx.HTTPError:
                        pass

    # --- 防火墙 filter 规则（一键放通场景使用）---

    async def list_filter_rules(self) -> list[dict]:
        """IPv4 / IPv6 是两张独立的表，返回时用 _family 标记来源。"""
        result: list[dict] = []
        for family, path in (("v4", "/ip/firewall/filter"),
                             ("v6", "/ipv6/firewall/filter")):
            try:
                rules = await self._get(path)
            except Exception:
                if family == "v6":
                    continue  # 没有 IPv6 表/权限时忽略
                raise
            if isinstance(rules, list):
                for rule in rules:
                    item = dict(rule)
                    item["_family"] = family
                    result.append(item)
        return result

    async def add_filter_rule(self, fields: dict, place_before: str | None = None,
                              family: str = "v4") -> dict:
        path = "/ipv6/firewall/filter" if family == "v6" else "/ip/firewall/filter"
        body = dict(fields)
        body.setdefault("comment", self.MANAGED_TAG)
        if place_before:
            body["place-before"] = place_before
        return await self._put(path, body)

    async def remove_filter_rule(self, rule_id: str, family: str = "v4") -> None:
        path = "/ipv6/firewall/filter" if family == "v6" else "/ip/firewall/filter"
        await self._delete(f"{path}/{rule_id}")

    async def list_interface_list_members(self) -> list[dict]:
        """接口列表成员（LAN / WAN），用于判断哪些口是 LAN、哪些是 WAN。"""
        members = await self._get("/interface/list/member")
        return members if isinstance(members, list) else []

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()








