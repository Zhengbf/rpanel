from __future__ import annotations
from typing import Protocol, AsyncIterator
from pydantic import BaseModel


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    routeros_version: str | None = None
    identity: str | None = None
    can_read: bool = False
    can_write: bool = False


class SystemResource(BaseModel):
    version: str = ""
    cpu_load: float = 0.0
    free_memory: int = 0
    total_memory: int = 0
    uptime: str = ""
    disk_free: int = 0
    disk_total: int = 0
    cpu_count: int = 0


class InterfaceInfo(BaseModel):
    id: str = ""
    name: str = ""
    type: str = ""
    running: bool = False
    disabled: bool = False


class TrafficSample(BaseModel):
    interface: str
    rx_bits_per_second: float = 0.0
    tx_bits_per_second: float = 0.0
    rx_packets: float = 0.0
    tx_packets: float = 0.0


class ConnectionEntry(BaseModel):
    id: str = ""
    protocol: str = ""
    src_address: str = ""
    dst_address: str = ""
    src_ip: str = ""
    src_port: int | None = None
    dst_ip: str = ""
    dst_port: int | None = None
    state: str = ""
    orig_bytes: int = 0
    reply_bytes: int = 0
    total_bytes: int = 0
    reply_src_ip: str = ""
    reply_src_port: int | None = None
    reply_dst_ip: str = ""
    reply_dst_port: int | None = None
    orig_rate: float = 0.0      # bytes/s（由 RouterOS orig-rate 换算）
    repl_rate: float = 0.0
    fasttrack_bytes: int = 0
    connection_mark: str = ""
    timeout: str = ""


class ArpEntry(BaseModel):
    id: str = ""
    address: str = ""
    mac_address: str = ""
    interface: str = ""
    complete: bool = False


class DhcpServer(BaseModel):
    id: str = ""
    name: str = ""
    interface: str = ""
    address_pool: str = ""
    lease_time: str = ""
    disabled: bool = False
    dynamic: bool = False


class IpPool(BaseModel):
    id: str = ""
    name: str = ""
    ranges: str = ""
    comment: str = ""


class DhcpNetwork(BaseModel):
    id: str = ""
    address: str = ""
    gateway: str = ""
    netmask: str = ""
    dns_server: str = ""
    domain: str = ""
    comment: str = ""


class DhcpLease(BaseModel):
    id: str = ""
    address: str = ""
    mac_address: str = ""
    host_name: str = ""
    server: str = ""
    status: str = ""
    active: bool = False
    last_seen: str = ""
    expires_after: str = ""
    comment: str = ""
    dynamic: bool = False        # True=动态租约（可转静态），False=静态绑定
    disabled: bool = False
    blocked: bool = False


class FirewallState(BaseModel):
    blocked_ips: list[str] = []
    managed_rules: list[dict] = []
    other_rules_count: int = 0


class PortForward(BaseModel):
    id: str = ""
    protocol: str = ""
    dst_address: str = ""
    dst_port: str = ""
    to_addresses: str = ""
    to_ports: str = ""
    in_interface: str = ""
    comment: str = ""
    disabled: bool = False


class RouterOsClient(Protocol):
    async def test_connection(self) -> ConnectionTestResult: ...
    async def get_system_resource(self) -> SystemResource: ...
    async def get_identity(self) -> str: ...
    async def list_interfaces(self) -> list[InterfaceInfo]: ...
    async def get_interface_counters(self) -> dict[str, dict[str, int]]: ...
    async def monitor_traffic(self, iface: str) -> AsyncIterator[TrafficSample]: ...
    async def list_connections(self) -> list[ConnectionEntry]: ...
    async def list_arp(self) -> list[ArpEntry]: ...
    async def list_leases(self) -> list[DhcpLease]: ...
    async def add_block(self, ip: str, wan_interfaces: list[str]) -> None: ...
    async def remove_block(self, ip: str, wan_interfaces: list[str]) -> None: ...
    async def list_blocked(self) -> list[str]: ...
    async def get_firewall_state(self) -> FirewallState: ...
    # --- 防火墙 filter 规则（网络页「防火墙」一键放通使用）---
    async def list_filter_rules(self) -> list[dict]: ...
    async def add_filter_rule(self, fields: dict, place_before: str | None = None) -> dict: ...
    async def remove_filter_rule(self, rule_id: str) -> None: ...
    async def list_interface_list_members(self) -> list[dict]: ...
    async def get_ip_addresses(self) -> list[dict]: ...
    async def export_config(self, sensitive: bool = False) -> str: ...
    # --- DHCP 管理（网络页使用；后续新功能按同样方式扩展协议）---
    async def list_dhcp_servers(self) -> list[DhcpServer]: ...
    async def list_dhcp_networks(self) -> list[DhcpNetwork]: ...
    async def make_lease_static(self, lease_id: str) -> None: ...
    async def add_static_lease(self, address: str, mac_address: str, server: str = "",
                               comment: str = "", host_name: str = "") -> None: ...
    async def remove_lease(self, lease_id: str) -> None: ...
    async def set_lease(self, lease_id: str, fields: dict) -> None: ...
    async def add_dhcp_network(self, address: str, gateway: str = "", netmask: str = "",
                               dns_server: str = "", domain: str = "", comment: str = "") -> None: ...
    async def set_dhcp_network(self, network_id: str, fields: dict) -> None: ...
    async def remove_dhcp_network(self, network_id: str) -> None: ...
    async def list_ip_pools(self) -> list[IpPool]: ...
    async def add_ip_pool(self, name: str, ranges: str, comment: str = "") -> None: ...
    async def set_ip_pool(self, pool_id: str, fields: dict) -> None: ...
    async def remove_ip_pool(self, pool_id: str) -> None: ...
    async def add_dhcp_server(self, name: str, interface: str, address_pool: str = "",
                              lease_time: str = "1d") -> None: ...
    async def set_dhcp_server(self, server_id: str, fields: dict) -> None: ...
    async def remove_dhcp_server(self, server_id: str) -> None: ...
    async def list_port_forwards(self) -> list[PortForward]: ...
    async def add_port_forward(self, *, protocol: str, dst_port: str, to_addresses: str,
                               to_ports: str = "", in_interface: str = "", comment: str = "") -> None: ...
    async def set_port_forward(self, rule_id: str, fields: dict) -> None: ...
    async def remove_port_forward(self, rule_id: str) -> None: ...
    async def clear_connections(self, ip: str) -> None: ...
    async def close(self) -> None: ...





