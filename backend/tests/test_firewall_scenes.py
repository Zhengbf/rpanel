"""一键放通场景的语义与安全性：位置、幂等、不动用户规则、WAN/LAN 识别。"""
import pytest

from app.services import firewall_scenes as fs


class FakeClient:
    def __init__(self, rules=None, wans=("wan1",), lans=("bridge",)):
        self.rules = [dict(r) for r in (rules or [])]
        self._next = 1
        members = [{"list": "WAN", "interface": w} for w in wans]
        members += [{"list": "LAN", "interface": lan} for lan in lans]
        self._members = members

    async def list_filter_rules(self):
        return [dict(r) for r in self.rules]

    async def list_interface_list_members(self):
        return list(self._members)

    async def add_filter_rule(self, fields, place_before=None, family="v4"):
        rid = f"*T{family}{self._next}"
        self._next += 1
        rule = {".id": rid, "_family": family, **fields}
        index = len(self.rules)
        if place_before:
            for i, existing in enumerate(self.rules):
                if existing.get(".id") == place_before:
                    index = i
                    break
        self.rules.insert(index, rule)
        return rule

    async def remove_filter_rule(self, rule_id, family="v4"):
        self.rules = [r for r in self.rules
                      if not (r.get(".id") == rule_id
                              and r.get("_family", "v4") == family)]


def base_rules():
    return [
        {".id": "*1", "chain": "input", "action": "accept", "comment": "established"},
        {".id": "*2", "chain": "input", "action": "drop", "comment": "deny"},
        {".id": "*3", "chain": "forward", "action": "accept", "comment": "established"},
        {".id": "*4", "chain": "forward", "action": "drop", "comment": "deny"},
    ]


def index_of(rules, predicate):
    return next(i for i, r in enumerate(rules) if predicate(r))


@pytest.mark.asyncio
async def test_allow_port_creates_both_chains_before_drop():
    client = FakeClient(base_rules())
    result = await fs.allow_port(client, ["tcp"], "9233", "wan1")

    assert sorted(result["created"]) == ["tcp/v4/forward", "tcp/v4/input"]
    input_drop = index_of(client.rules, lambda r: r["chain"] == "input"
                          and r["action"] == "drop")
    forward_drop = index_of(client.rules, lambda r: r["chain"] == "forward"
                            and r["action"] == "drop")
    for chain, drop_idx in (("input", input_drop), ("forward", forward_drop)):
        idx = index_of(client.rules, lambda r, c=chain: r["chain"] == c
                       and r.get("dst-port") == "9233")
        assert idx < drop_idx
        assert client.rules[idx]["comment"] == fs.MANAGED_TAG


@pytest.mark.asyncio
async def test_allow_port_is_idempotent():
    client = FakeClient(base_rules())
    await fs.allow_port(client, ["tcp"], "9233", "wan1")
    before = len(client.rules)
    result = await fs.allow_port(client, ["tcp"], "9233", "wan1")

    assert len(client.rules) == before
    assert result["created"] == []
    assert sorted(result["existed"]) == ["tcp/v4/forward", "tcp/v4/input"]


@pytest.mark.asyncio
async def test_revoke_removes_only_managed_rules():
    client = FakeClient(base_rules())
    await fs.allow_port(client, ["tcp"], "9233", "wan1")
    result = await fs.revoke_port(client, ["tcp"], "9233", "wan1")

    assert len(result["removed"]) == 2
    assert not [r for r in client.rules if r.get("dst-port") == "9233"]
    assert result["user_rule_left"] is False


@pytest.mark.asyncio
async def test_port_family_is_explicit():
    """放通必须写明地址族：默认只放 IPv4，不能顺带把 IPv6 暴露出去。"""
    client = FakeClient(base_rules())
    await fs.allow_port(client, ["tcp"], "9233", "wan1", "v4")
    v4 = [r for r in client.rules if r.get("dst-port") == "9233"]
    assert len(v4) == 2
    assert all(r.get("src-address") == "0.0.0.0/0" for r in v4)
    assert not [r for r in client.rules if r.get("src-address") == "::/0"]

    client2 = FakeClient(base_rules())
    await fs.allow_port(client2, ["tcp"], "9233", "wan1", "v6")
    v6 = [r for r in client2.rules if r.get("dst-port") == "9233"]
    assert len(v6) == 2
    assert all(r.get("src-address") == "::/0" for r in v6)

    client3 = FakeClient(base_rules())
    both = await fs.allow_port(client3, ["tcp"], "9233", "wan1", "both")
    assert len(both["created"]) == 4
    assert {r.get("src-address") for r in client3.rules
            if r.get("dst-port") == "9233"} == {"0.0.0.0/0", "::/0"}


@pytest.mark.asyncio
async def test_revoke_one_family_keeps_the_other():
    client = FakeClient(base_rules())
    await fs.allow_port(client, ["tcp"], "9233", "wan1", "both")
    removed = await fs.revoke_port(client, ["tcp"], "9233", "wan1", "v4")
    assert len(removed["removed"]) == 2
    left = [r for r in client.rules if r.get("dst-port") == "9233"]
    assert len(left) == 2
    assert all(r.get("src-address") == "::/0" for r in left)


@pytest.mark.asyncio
async def test_old_v4_only_rule_does_not_mark_v6_allowed():
    """老版本建的规则没有 src-address，但它落在 IPv4 表里，只代表 v4 放通。"""
    rules = [
        {".id": "*1", "chain": "input", "action": "accept", "comment": "established"},
        {".id": "*8", "chain": "input", "action": "accept", "protocol": "tcp",
         "dst-port": "9233", "in-interface": "wan1",
         "comment": fs.MANAGED_TAG},
        {".id": "*2", "chain": "input", "action": "drop", "comment": "deny"},
        {".id": "*3", "chain": "forward", "action": "accept", "comment": "established"},
        {".id": "*4", "chain": "forward", "action": "drop", "comment": "deny"},
    ]
    status = await fs.build_status(FakeClient(rules))
    row = next(p for p in status["scenes"]["port_rules"] if p["ports"] == "9233")
    assert row["v4"]["allowed"] is True
    assert row["v6"]["allowed"] is False


@pytest.mark.asyncio
async def test_user_rule_counts_as_allowed_and_is_never_deleted():
    # 用户自己写的等效规则，位置在 drop 之前（真正生效）
    rules = [
        {".id": "*1", "chain": "input", "action": "accept", "comment": "established"},
        {".id": "*9", "chain": "input", "action": "accept", "protocol": "tcp",
         "dst-port": "9233", "in-interface": "wan1", "comment": "我的规则"},
        {".id": "*2", "chain": "input", "action": "drop", "comment": "deny"},
        {".id": "*3", "chain": "forward", "action": "accept", "comment": "established"},
        {".id": "*A", "chain": "forward", "action": "accept", "protocol": "tcp",
         "dst-port": "9233", "in-interface": "wan1", "comment": "我的规则"},
        {".id": "*4", "chain": "forward", "action": "drop", "comment": "deny"},
    ]
    client = FakeClient(rules)
    allowed = await fs.allow_port(client, ["tcp"], "9233", "wan1")
    assert allowed["created"] == []

    revoked = await fs.revoke_port(client, ["tcp"], "9233", "wan1")
    assert revoked["removed"] == []
    assert revoked["user_rule_left"] is True
    assert len([r for r in client.rules if r.get("dst-port") == "9233"]) == 2


@pytest.mark.asyncio
async def test_accept_after_drop_is_not_effective():
    rules = base_rules() + [
        {".id": "*7", "chain": "input", "action": "accept", "protocol": "tcp",
         "dst-port": "9233", "in-interface": "wan1", "comment": "错位的规则"},
    ]
    client = FakeClient(rules)
    result = await fs.allow_port(client, ["tcp"], "9233", "wan1")

    # forward 需要新建；input 因为原规则在 drop 之后，也必须新建一条在 drop 之前
    assert "tcp/v4/input" in result["created"]
    input_drop = index_of(client.rules, lambda r: r["chain"] == "input"
                          and r["action"] == "drop")
    managed = [r for r in client.rules if r.get("chain") == "input"
               and r.get("comment") == fs.MANAGED_TAG]
    assert managed and client.rules.index(managed[0]) < input_drop


@pytest.mark.asyncio
async def test_wan_all_v4_and_v6():
    client = FakeClient(base_rules())
    await fs.set_wan_all(client, True, "wan1", "both")
    v4 = [r for r in client.rules if r.get("_family", "v4") == "v4"
          and r.get("src-address") == "0.0.0.0/0"]
    v6 = [r for r in client.rules if r.get("_family") == "v6"]
    assert len(v4) == 2 and len(v6) == 2
    assert {r["chain"] for r in v4} == {"input", "forward"}

    result = await fs.set_wan_all(client, False, "wan1", "v4")
    assert len(result["changed"]) == 2
    assert not [r for r in client.rules if r.get("_family", "v4") == "v4"
                and r.get("src-address") == "0.0.0.0/0"]
    assert len([r for r in client.rules if r.get("_family") == "v6"]) == 2


@pytest.mark.asyncio
async def test_wan_all_recognises_handwritten_rule_without_src_address():
    """手写的 in-interface=wan + accept（不写 src-address）就是 IPv4 的 WAN→ALL。"""
    rules = [
        {".id": "*1", "chain": "input", "action": "accept", "comment": "established"},
        {".id": "*2", "chain": "input", "action": "drop", "comment": "deny"},
        {".id": "*3", "chain": "forward", "action": "accept", "comment": "established"},
        {".id": "*9", "chain": "forward", "action": "accept",
         "in-interface": "wan1", "comment": "wan1-in"},
        {".id": "*4", "chain": "forward", "action": "drop", "comment": "deny"},
    ]
    status = await fs.build_status(FakeClient(rules))
    entry = next(w for w in status["scenes"]["wan_all"] if w["wan"] == "wan1")
    assert entry["v4"]["allowed"] is True
    assert entry["v4"]["user_rule"] is True
    assert entry["v4"]["managed"] is False
    # /ip/firewall/filter 是 IPv4 表，不能顺带把 IPv6 也算成已放通
    assert entry["v6"]["allowed"] is False


@pytest.mark.asyncio
async def test_ipv6_table_rules_count_for_v6_only():
    rules = [
        {".id": "*1", "_family": "v6", "chain": "forward", "action": "accept",
         "in-interface": "wan1", "comment": "我的 v6 放通"},
    ]
    status = await fs.build_status(FakeClient(rules))
    entry = next(w for w in status["scenes"]["wan_all"] if w["wan"] == "wan1")
    assert entry["v6"]["allowed"] is True
    assert entry["v4"]["allowed"] is False


@pytest.mark.asyncio
async def test_wan_all_ignores_rules_with_extra_conditions():
    rules = [
        {".id": "*1", "chain": "forward", "action": "accept", "comment": "established"},
        {".id": "*2", "chain": "forward", "action": "accept", "in-interface": "wan1",
         "connection-state": "established,related", "comment": "只放已建立"},
        {".id": "*3", "chain": "forward", "action": "accept", "in-interface": "wan1",
         "protocol": "tcp", "dst-port": "80", "comment": "只放 80"},
        {".id": "*4", "chain": "forward", "action": "drop", "comment": "deny"},
    ]
    status = await fs.build_status(FakeClient(rules))
    entry = next(w for w in status["scenes"]["wan_all"] if w["wan"] == "wan1")
    assert entry["v4"]["allowed"] is False


@pytest.mark.asyncio
async def test_wan_all_recognises_interface_list_wan():
    rules = [
        {".id": "*1", "chain": "forward", "action": "accept",
         "in-interface-list": "WAN", "comment": "我的整组放通"},
    ]
    status = await fs.build_status(FakeClient(rules))
    entry = next(w for w in status["scenes"]["wan_all"] if w["wan"] == "wan1")
    assert entry["v4"]["allowed"] is True


@pytest.mark.asyncio
async def test_lan_all_uses_interface_list_and_protects_user_rules():
    client = FakeClient(base_rules())
    await fs.set_lan_all(client, True)
    managed = [r for r in client.rules if r.get("comment") == fs.MANAGED_TAG]
    assert len(managed) == 4  # v4 / v6 各自 input + forward
    assert all(r.get("in-interface-list") == "LAN" for r in managed)
    assert {r.get("_family", "v4") for r in managed} == {"v4", "v6"}

    client.rules.append({".id": "*U", "chain": "input", "action": "accept",
                         "in-interface-list": "LAN", "comment": "用户自己的 LAN 放行"})
    result = await fs.set_lan_all(client, False)
    assert result["user_rule_left"] is True
    assert [r for r in client.rules if r.get(".id") == "*U"]
    assert not [r for r in client.rules if r.get("comment") == fs.MANAGED_TAG]


@pytest.mark.asyncio
async def test_wan_list_excludes_interfaces_that_are_also_lan():
    client = FakeClient(base_rules(), wans=("wan1", "wg1"),
                        lans=("bridge", "wg1"))
    sets = await fs.interface_sets(client)
    assert sets["wans"] == ["wan1"]
    assert "wg1" in sets["lans"]


@pytest.mark.asyncio
async def test_unknown_wan_is_rejected():
    client = FakeClient(base_rules())
    with pytest.raises(ValueError):
        await fs.allow_port(client, ["tcp"], "9233", "no-such-wan")
    with pytest.raises(ValueError):
        await fs.set_wan_all(client, True, "no-such-wan", "v4")
