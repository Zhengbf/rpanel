"""网络服务层单测：用假 RouterOsClient，不依赖真实路由器。"""
import pytest

from app.adapters.ros.base import DhcpLease, DhcpNetwork, DhcpServer, IpPool
from app.services.network import NetworkService


class FakeRosClient:
    """只实现 NetworkService 用到的方法，语义与真实适配器一致。"""

    def __init__(self):
        self.leases = [
            DhcpLease(id="*1", address="192.168.88.50", mac_address="AA:BB:CC:DD:EE:01",
                      host_name="cam", server="dhcp-lan", status="bound", dynamic=True),
            DhcpLease(id="*2", address="192.168.88.3", mac_address="AA:BB:CC:DD:EE:02",
                      host_name="nas", server="dhcp-lan", status="bound", dynamic=False),
        ]
        self.made_static: list[str] = []
        self.added: list[tuple] = []
        self.removed: list[str] = []

    async def list_leases(self):
        return self.leases

    async def list_dhcp_servers(self):
        return getattr(self, "servers", [DhcpServer(id="*1", name="dhcp-lan", interface="bridge",
                                                    address_pool="dhcp-lan", lease_time="1d")])

    async def list_dhcp_networks(self):
        return [DhcpNetwork(id="*1", address="192.168.88.0/24", gateway="192.168.88.1",
                            dns_server="192.168.88.2")]

    async def make_lease_static(self, lease_id: str):
        self.made_static.append(lease_id)

    async def add_static_lease(self, address, mac_address, server="", comment="", host_name=""):
        self.added.append((address, mac_address, server, comment))

    async def remove_lease(self, lease_id: str):
        self.removed.append(lease_id)

    async def list_ip_pools(self):
        return [IpPool(id="*1", name="dhcp-lan", ranges="192.168.88.100-192.168.88.200", comment="")]

    async def add_ip_pool(self, name, ranges, comment=""):
        self.pools_added = getattr(self, "pools_added", [])
        self.pools_added.append((name, ranges))
        self.ip_pools = getattr(self, "ip_pools", [])
        self.ip_pools.append(IpPool(id="*9", name=name, ranges=ranges))

    async def set_ip_pool(self, pool_id, fields):
        self.pools_set = getattr(self, "pools_set", [])
        self.pools_set.append((pool_id, fields))

    async def remove_ip_pool(self, pool_id):
        self.pools_removed = getattr(self, "pools_removed", [])
        self.pools_removed.append(pool_id)

    async def add_dhcp_server(self, name, interface, address_pool="", lease_time="1d"):
        self.servers_added = getattr(self, "servers_added", [])
        self.servers_added.append((name, interface, address_pool, lease_time))

    async def set_dhcp_server(self, server_id, fields):
        self.servers_set = getattr(self, "servers_set", [])
        self.servers_set.append((server_id, fields))

    async def set_lease(self, lease_id, fields):
        self.lease_sets = getattr(self, "lease_sets", [])
        self.lease_sets.append((lease_id, fields))

    async def add_dhcp_network(self, address, gateway="", netmask="", dns_server="", domain="", comment=""):
        self.networks_added = getattr(self, "networks_added", [])
        self.networks_added.append((address, gateway, dns_server))

    async def set_dhcp_network(self, network_id, fields):
        self.networks_set = getattr(self, "networks_set", [])
        self.networks_set.append((network_id, fields))

    async def remove_dhcp_network(self, network_id):
        self.networks_removed = getattr(self, "networks_removed", [])
        self.networks_removed.append(network_id)

    async def remove_dhcp_server(self, server_id):
        self.servers_removed = getattr(self, "servers_removed", [])
        self.servers_removed.append(server_id)


class FakeDb:
    def __init__(self):
        self.logs = []

    def add(self, obj):
        self.logs.append(obj)

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_leases_marks_dynamic_and_static():
    svc = NetworkService(FakeRosClient())
    leases = await svc.leases()
    assert [l["is_static"] for l in leases] == [True, False]   # 静态排前面
    assert leases[0]["id"] == "*2"
    assert leases[1]["dynamic"] is True
    # 字段契约（前端依赖）
    for key in ("id", "address", "mac", "hostname", "server", "dynamic", "is_static", "last_seen"):
        assert key in leases[0]


@pytest.mark.asyncio
async def test_make_static_calls_adapter_and_audits():
    client = FakeRosClient()
    db = FakeDb()
    await NetworkService(client).make_static(db, "*1", 1, "admin")
    assert client.made_static == ["*1"]
    assert db.logs and db.logs[0].action == "dhcp_make_static"


@pytest.mark.asyncio
async def test_add_static_passes_fields():
    client = FakeRosClient()
    db = FakeDb()
    await NetworkService(client).add_static(db, "192.168.88.60", "AA:BB:CC:DD:EE:03",
                                            "dhcp-lan", "客厅摄像头", 1, "admin")
    assert client.added == [("192.168.88.60", "AA:BB:CC:DD:EE:03", "dhcp-lan", "客厅摄像头")]
    assert db.logs[0].action == "dhcp_add_static"


@pytest.mark.asyncio
async def test_dhcp_overview_shape():
    ov = await NetworkService(FakeRosClient()).dhcp_overview()
    assert ov["servers"][0]["name"] == "dhcp-lan"
    assert ov["networks"][0]["gateway"] == "192.168.88.1"
    assert ov["pools"][0]["ranges"] == "192.168.88.100-192.168.88.200"



@pytest.mark.asyncio
async def test_add_dhcp_server_passes_fields_and_audits():
    client = FakeRosClient()
    db = FakeDb()
    await NetworkService(client).add_server(db, "dhcp-guest", "bridge-guest", "pool-guest", "12h", 1, "admin")
    assert client.servers_added == [("dhcp-guest", "bridge-guest", "pool-guest", "12h")]
    assert db.logs[0].action == "dhcp_add_server"


@pytest.mark.asyncio
async def test_update_dhcp_server():
    client = FakeRosClient()
    db = FakeDb()
    await NetworkService(client).set_server(db, "*1", {"name": "dhcp-lan2", "lease_time": "2d"}, 1, "admin")
    assert client.servers_set == [("*1", {"name": "dhcp-lan2", "lease_time": "2d"})]
    assert db.logs[0].action == "dhcp_set_server"


@pytest.mark.asyncio
async def test_remove_dhcp_server():
    client = FakeRosClient()
    db = FakeDb()
    await NetworkService(client).remove_server(db, "*9", 1, "admin")
    assert client.servers_removed == ["*9"]
    assert db.logs[0].action == "dhcp_remove_server"


# ---------- 静态绑定的两种情况 ----------

@pytest.mark.asyncio
async def test_add_static_when_mac_has_dynamic_lease_converts_then_moves():
    """已分配的设备改地址：应先 make-static，再 set address（否则 RouterOS 会拒绝）。"""
    client = FakeRosClient()
    db = FakeDb()
    svc = NetworkService(client)
    # 动态租约：AA:...:01 当前在 192.168.88.50，用户想绑到 192.168.88.199
    await svc.add_static(db, "192.168.88.199", "AA:BB:CC:DD:EE:01", "dhcp-lan", "", 1, "admin")
    assert client.made_static == ["*1"]                       # 先转静态
    assert client.lease_sets and client.lease_sets[0][1]["address"] == "192.168.88.199"
    assert not getattr(client, "added", [])                    # 不应再 add 一条新的
    assert db.logs[0].action == "dhcp_add_static"


@pytest.mark.asyncio
async def test_add_static_rejects_ip_used_by_other_device():
    client = FakeRosClient()
    db = FakeDb()
    # 192.168.88.3 已被另一个 MAC（...02）静态占用
    with pytest.raises(ValueError):
        await NetworkService(client).add_static(db, "192.168.88.3", "AA:BB:CC:DD:EE:99", "", "", 1, "admin")


@pytest.mark.asyncio
async def test_add_static_for_unknown_mac_creates_new_lease():
    client = FakeRosClient()
    db = FakeDb()
    await NetworkService(client).add_static(db, "192.168.88.240", "AA:BB:CC:DD:EE:77", "dhcp-lan", "新设备", 1, "admin")
    assert client.added == [("192.168.88.240", "AA:BB:CC:DD:EE:77", "dhcp-lan", "新设备")]
    assert not client.made_static


# ---------- 网段 CRUD ----------

@pytest.mark.asyncio
async def test_network_crud():
    client = FakeRosClient()
    db = FakeDb()
    svc = NetworkService(client)
    await svc.add_network(db, "192.168.9.0/24", "192.168.9.1", "", "192.168.9.1,223.5.5.5", "", "访客网段", 1, "admin")
    assert client.networks_added == [("192.168.9.0/24", "192.168.9.1", "192.168.9.1,223.5.5.5")]
    await svc.set_network(db, "*1", {"gateway": "192.168.88.254"}, 1, "admin")
    assert client.networks_set == [("*1", {"gateway": "192.168.88.254"})]
    await svc.remove_network(db, "*2", 1, "admin")
    assert client.networks_removed == ["*2"]
    assert [log.action for log in db.logs] == ["dhcp_add_network", "dhcp_set_network", "dhcp_remove_network"]


# ---------- 一站式创建：顺序与幂等 ----------

@pytest.mark.asyncio
async def test_provision_creates_pool_then_network_then_server():
    """全新环境：三步都应新建，且顺序必须是 pool → network → server。"""
    client = FakeRosClient()
    client.leases = []
    client.servers = []          # 没有 DHCP 服务器
    db = FakeDb()

    async def no_networks():
        return []
    client.list_dhcp_networks = no_networks

    async def no_pools():
        return []
    client.list_ip_pools = no_pools

    res = await NetworkService(client).provision_dhcp(
        db, network_cidr="192.168.9.0/24", gateway="192.168.9.1",
        pool_name="dhcp-guest", pool_ranges="192.168.9.100-192.168.9.200",
        server_name="dhcp-guest", interface="bridge", dns_server="192.168.9.1,223.5.5.5",
        lease_time="12h", comment="", operator_id=1, operator_name="admin")

    assert [st["step"] for st in res["steps"]] == ["pool", "network", "server"]
    assert all(st["action"] == "created" for st in res["steps"])
    assert client.pools_added == [("dhcp-guest", "192.168.9.100-192.168.9.200")]
    assert client.networks_added[0][0] == "192.168.9.0/24"
    assert client.servers_added[0][0] == "dhcp-guest"
    assert client.servers_added[0][2] == "dhcp-guest"     # 服务器绑定到刚建的池
    assert db.logs[-1].action == "dhcp_provision"


@pytest.mark.asyncio
async def test_provision_is_idempotent_when_everything_exists():
    """重复提交：同名池/同网段/同名服务器都存在时只做更新，不重复创建，可安全重试。"""
    client = FakeRosClient()
    db = FakeDb()
    res = await NetworkService(client).provision_dhcp(
        db, network_cidr="192.168.88.0/24", gateway="192.168.88.1",
        pool_name="dhcp-lan", pool_ranges="192.168.88.100-192.168.88.200",
        server_name="dhcp-lan", interface="bridge", dns_server="192.168.88.2,223.5.5.5",
        lease_time="1d", comment="", operator_id=1, operator_name="admin")

    actions = {st["step"]: st["action"] for st in res["steps"]}
    assert actions["pool"] == "exists"           # 同名同范围 → 复用
    assert actions["server"] == "exists"         # 同名且接口/池一致 → 复用
    assert not getattr(client, "pools_added", [])
    assert not getattr(client, "servers_added", [])


@pytest.mark.asyncio
async def test_provision_refuses_to_overwrite_other_subnet_pool():
    """同名地址池但范围不同 → 必须报错，不能覆盖别人在用的池。"""
    client = FakeRosClient()
    db = FakeDb()
    with pytest.raises(ValueError) as ei:
        await NetworkService(client).provision_dhcp(
            db, network_cidr="192.168.88.0/24", gateway="192.168.88.1",
            pool_name="dhcp-lan",                       # 已存在，但范围是 192.168.88.x
            pool_ranges="192.168.88.100-192.168.88.200",
            server_name="dhcp-88", interface="bridge", dns_server="192.168.88.1",
            lease_time="1d", comment="", operator_id=1, operator_name="admin")
    assert "范围不同" in str(ei.value)
    assert not getattr(client, "pools_set", [])         # 绝不能去改现有池


@pytest.mark.asyncio
async def test_provision_refuses_to_overwrite_existing_server():
    """同名 DHCP 服务器但绑定关系不同 → 报错而不是覆盖。"""
    client = FakeRosClient()
    client.servers = [DhcpServer(id="*1", name="dhcp-lan", interface="bridge",
                                 address_pool="pool-a", lease_time="1d")]
    db = FakeDb()
    with pytest.raises(ValueError) as ei:
        await NetworkService(client).provision_dhcp(
            db, network_cidr="192.168.88.0/24", gateway="192.168.88.1",
            pool_name="dhcp-lan", pool_ranges="192.168.88.100-192.168.88.200",
            server_name="dhcp-lan", interface="bridge", dns_server="192.168.88.1",
            lease_time="1d", comment="", operator_id=1, operator_name="admin")
    assert "已存在" in str(ei.value)
    assert not getattr(client, "servers_added", [])
