import pytest
from app.services.firewall import FirewallService


class FakeRosClient:
    def __init__(self):
        self.blocked: set[str] = set()
        self.rule_exists = False
        self.cleared: list[str] = []

    async def add_block(self, ip, wan):
        self.blocked.add(ip)
        self.rule_exists = True

    async def remove_block(self, ip, wan):
        self.blocked.discard(ip)
        if not self.blocked:
            self.rule_exists = False

    async def list_blocked(self):
        return sorted(self.blocked)

    async def clear_connections(self, ip):
        self.cleared.append(ip)


class FakeDb:
    def __init__(self):
        self.blocked: dict[str, object] = {}
        self.logs = []

    async def get(self, model, ip):
        return self.blocked.get(ip)

    def add(self, obj):
        if hasattr(obj, 'ip') and hasattr(obj, 'blocked_by'):
            self.blocked[obj.ip] = obj
        elif hasattr(obj, 'action'):
            self.logs.append(obj)

    async def delete(self, obj):
        self.blocked.pop(obj.ip, None)

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_block_idempotent():
    c = FakeRosClient()
    db = FakeDb()
    svc = FirewallService(c, ["pppoe-wan1"])
    await svc.block_ip(db, "192.168.8.100", 1, "admin")
    await svc.block_ip(db, "192.168.8.100", 1, "admin")
    assert c.blocked == {"192.168.8.100"}
    assert c.rule_exists is True


@pytest.mark.asyncio
async def test_block_clears_connections():
    c = FakeRosClient()
    db = FakeDb()
    svc = FirewallService(c, ["pppoe-wan1"])
    await svc.block_ip(db, "192.168.8.100", 1, "admin")
    assert "192.168.8.100" in c.cleared


@pytest.mark.asyncio
async def test_unblock_removes_rule_when_empty():
    c = FakeRosClient()
    db = FakeDb()
    svc = FirewallService(c, ["pppoe-wan1"])
    await svc.block_ip(db, "192.168.8.100", 1, "admin")
    await svc.unblock_ip(db, "192.168.8.100", 1, "admin")
    assert c.rule_exists is False
