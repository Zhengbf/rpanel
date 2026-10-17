"""一键放通：把常见的防火墙放通需求封装成场景。

约定（与前端页面对齐）：
- RouterOS 7 的 IPv4 / IPv6 防火墙是两张独立的表（/ip/firewall/filter 与
  /ipv6/firewall/filter），所以每条规则都必须带上地址族，不能混写。
- 端口放通在 input / forward 两个链各建一条同匹配的 accept，
  用户不需要理解"进到路由器"和"进到内网"的区别。
- 新规则插在该链第一条 drop / reject 之前——RouterOS 首条匹配即停，
  插在 drop 之后等于没放通。
- 判重按语义：用户自己写的等效规则也算"已放通"，不会重复创建；
  取消时只删带 managed-by=router-panel 标记的规则，绝不动用户的规则。
"""
from __future__ import annotations

from app.adapters.ros.base import RouterOsClient

MANAGED_TAG = "managed-by=router-panel"
CHAINS = ("input", "forward")
BLOCK_ACTIONS = {"drop", "reject"}
LAN_LIST_NAME = "LAN"
FAMILIES = ("v4", "v6")
ALL_SRC = {"v4": "0.0.0.0/0", "v6": "::/0"}


def _text(value) -> str:
    return str(value or "").strip()


def _blank(rule: dict, *keys: str) -> bool:
    return all(not _text(rule.get(k)) for k in keys)


def rule_family(rule: dict) -> str:
    """规则所属地址族：适配层会给每条规则打 _family 标记。"""
    return "v6" if _text(rule.get("_family")) == "v6" else "v4"


def _rid(rule: dict) -> tuple[str, str]:
    # 两张表的 .id 会重复（都是 *1 开始），必须带地址族一起用
    return (rule_family(rule), _text(rule.get(".id")))


def is_managed(rule: dict) -> bool:
    return MANAGED_TAG in _text(rule.get("comment"))


def first_blocker_id(rules: list[dict], chain: str, family: str) -> str | None:
    for rule in rules:
        if (rule_family(rule) == family and _text(rule.get("chain")) == chain
                and _text(rule.get("action")) in BLOCK_ACTIONS):
            return rule.get(".id")
    return None


def effective_rule_ids(rules: list[dict]) -> set[tuple[str, str]]:
    """accept 规则只有在"同一张表、同一条链"的第一条 drop/reject 之前才生效。"""
    blockers: dict[tuple[str, str], int] = {}
    for i, rule in enumerate(rules):
        chain = _text(rule.get("chain"))
        if chain not in CHAINS:
            continue
        key = (rule_family(rule), chain)
        if key not in blockers and _text(rule.get("action")) in BLOCK_ACTIONS:
            blockers[key] = i

    effective: set[tuple[str, str]] = set()
    for i, rule in enumerate(rules):
        if _text(rule.get("action")) != "accept":
            continue
        chain = _text(rule.get("chain"))
        if chain not in CHAINS:
            continue
        idx = blockers.get((rule_family(rule), chain))
        if _rid(rule)[1] and (idx is None or i < idx):
            effective.add(_rid(rule))
    return effective


def matches_port(rule: dict, protocol: str, ports: str, wan: str,
                 chain: str | None = None, family: str | None = None) -> bool:
    """chain 传了就只比对该链：input 和 forward 是两条独立规则，不能互相顶替。"""
    if family is not None and rule_family(rule) != family:
        return False
    return (
        _text(rule.get("action")) == "accept"
        and _text(rule.get("chain")) in CHAINS
        and (chain is None or _text(rule.get("chain")) == chain)
        and _text(rule.get("protocol")) == protocol
        and _text(rule.get("dst-port")).replace(" ", "") == ports.replace(" ", "")
        and _text(rule.get("in-interface")) == wan
    )


def matches_lan_all(rule: dict, lan_names: list[str], use_list: bool,
                    family: str | None = None) -> bool:
    if family is not None and rule_family(rule) != family:
        return False
    if _text(rule.get("action")) != "accept" or _text(rule.get("chain")) not in CHAINS:
        return False
    # 场景规则是"全放通"，任何额外匹配条件都说明不是同一条场景
    if not _blank(rule, "protocol", "dst-port", "src-address", "dst-address",
                  "src-address-list", "dst-address-list", "connection-state"):
        return False
    if use_list:
        return _text(rule.get("in-interface-list")).upper() == LAN_LIST_NAME
    return _text(rule.get("in-interface")) in lan_names


def matches_wan_all(rule: dict, wan: str, family: str) -> bool:
    if rule_family(rule) != family:
        return False
    if _text(rule.get("action")) != "accept" or _text(rule.get("chain")) not in CHAINS:
        return False
    # 入口既可以是具体 WAN 口，也可以是用 in-interface-list=WAN 写成整组
    by_iface = _text(rule.get("in-interface")) == wan
    by_list = _text(rule.get("in-interface-list")).upper() == "WAN"
    if not (by_iface or by_list):
        return False
    if not _blank(rule, "protocol", "dst-port", "dst-address",
                  "src-address-list", "dst-address-list", "connection-state"):
        return False
    src = _text(rule.get("src-address"))
    return not src or src == ALL_SRC[family]


async def interface_sets(client: RouterOsClient) -> dict:
    """返回 WAN / LAN 接口集合。

    WAN 会排除同时挂在 LAN 列表里的接口（例如 WireGuard 口既在 WAN 定义里、
    又被当作内网网段的情况），否则会把 VPN 当公网口一键放通。
    """
    lan_members: list[str] = []
    wan_members: list[str] = []
    try:
        members = await client.list_interface_list_members()
    except Exception:
        members = []
    for member in members:
        if _text(member.get("disabled")).lower() == "true":
            continue
        name = _text(member.get("interface"))
        list_name = _text(member.get("list")).upper()
        if not name:
            continue
        if list_name == LAN_LIST_NAME:
            lan_members.append(name)
        elif list_name == "WAN":
            wan_members.append(name)

    wans = [w for w in wan_members if w not in lan_members]
    if not wans:
        from app.services.sampler import detect_wan_interfaces
        try:
            wans = [w for w in await detect_wan_interfaces(client) if w not in lan_members]
        except Exception:
            wans = []
    return {
        "wans": wans,
        "lans": lan_members,
        "has_lan_list": bool(lan_members),
        "has_wan_list": bool(wan_members),
    }


def _serialize(rule: dict, effective: set[tuple[str, str]]) -> dict:
    return {
        "id": _text(rule.get(".id")),
        "family": rule_family(rule),
        "chain": _text(rule.get("chain")),
        "action": _text(rule.get("action")),
        "protocol": _text(rule.get("protocol")),
        "dst_port": _text(rule.get("dst-port")),
        "in_interface": _text(rule.get("in-interface")),
        "in_interface_list": _text(rule.get("in-interface-list")),
        "src_address": _text(rule.get("src-address")),
        "comment": _text(rule.get("comment")),
        "managed": is_managed(rule),
        "effective": _rid(rule) in effective,
    }


def _scene_state(rules: list[dict], effective: set[tuple[str, str]], predicate) -> dict:
    matched = [r for r in rules if predicate(r)]
    return {
        "allowed": any(_rid(r) in effective for r in matched),
        "managed": any(is_managed(r) for r in matched),
        "user_rule": any(not is_managed(r) for r in matched),
        "chains": sorted({_text(r.get("chain")) for r in matched
                          if _text(r.get("chain")) in CHAINS}),
    }


async def build_status(client: RouterOsClient) -> dict:
    rules = await client.list_filter_rules()
    effective = effective_rule_ids(rules)
    sets = await interface_sets(client)
    wans, lans = sets["wans"], sets["lans"]
    use_lan_list = sets["has_lan_list"]

    # 已存在的端口放通（含用户自建），按 协议+端口+WAN 归组，再分地址族
    ports_map: dict[tuple[str, str, str], dict] = {}
    for rule in rules:
        if _text(rule.get("action")) != "accept":
            continue
        if not _text(rule.get("protocol")) or not _text(rule.get("dst-port")):
            continue
        if not _text(rule.get("in-interface")):
            continue
        key = (_text(rule.get("protocol")), _text(rule.get("dst-port")),
               _text(rule.get("in-interface")))
        entry = ports_map.setdefault(key, {
            "protocol": key[0], "ports": key[1], "wan": key[2],
            "managed": False, "user_rule": False, "chains": [],
            "v4": {"allowed": False, "managed": False, "user_rule": False},
            "v6": {"allowed": False, "managed": False, "user_rule": False},
        })
        fam = rule_family(rule)
        entry["managed"] = entry["managed"] or is_managed(rule)
        entry["user_rule"] = entry["user_rule"] or not is_managed(rule)
        if _rid(rule) in effective:
            entry[fam]["allowed"] = True
            if is_managed(rule):
                entry[fam]["managed"] = True
            else:
                entry[fam]["user_rule"] = True
        chain = _text(rule.get("chain"))
        if chain and chain not in entry["chains"]:
            entry["chains"].append(chain)

    lan_all = {
        fam: _scene_state(rules, effective,
                          lambda r, f=fam: matches_lan_all(r, lans, use_lan_list, f))
        for fam in FAMILIES
    }
    wan_all = [
        {
            "wan": wan,
            "v4": _scene_state(rules, effective,
                               lambda r, w=wan: matches_wan_all(r, w, "v4")),
            "v6": _scene_state(rules, effective,
                               lambda r, w=wan: matches_wan_all(r, w, "v6")),
        }
        for wan in wans
    ]

    return {
        "wans": wans,
        "lans": lans,
        "has_lan_list": use_lan_list,
        "has_wan_list": sets["has_wan_list"],
        "rules": [_serialize(r, effective) for r in rules
                  if _text(r.get("chain")) in CHAINS],
        "scenes": {
            "port_rules": sorted(ports_map.values(),
                                 key=lambda x: (x["wan"], x["ports"], x["protocol"])),
            "lan_all": lan_all,
            "wan_all": wan_all,
        },
    }


async def allow_port(client: RouterOsClient, protocols: list[str], ports: str,
                     wan: str, family: str = "v4") -> dict:
    sets = await interface_sets(client)
    if wan not in sets["wans"]:
        raise ValueError(f"{wan} 不是可用的 WAN 接口")
    families = list(FAMILIES) if family == "both" else [family]

    created: list[str] = []
    existed: list[str] = []
    for protocol in protocols:
        for fam in families:
            for chain in CHAINS:
                rules = await client.list_filter_rules()
                effective = effective_rule_ids(rules)
                if any(matches_port(r, protocol, ports, wan, chain, fam)
                       and _rid(r) in effective for r in rules):
                    existed.append(f"{protocol}/{fam}/{chain}")
                    continue
                await client.add_filter_rule(
                    {"chain": chain, "action": "accept", "protocol": protocol,
                     "dst-port": ports, "in-interface": wan,
                     "src-address": ALL_SRC[fam], "comment": MANAGED_TAG},
                    place_before=first_blocker_id(rules, chain, fam),
                    family=fam,
                )
                created.append(f"{protocol}/{fam}/{chain}")
    return {"created": created, "existed": existed, "user_rule_left": False}


async def revoke_port(client: RouterOsClient, protocols: list[str], ports: str,
                      wan: str, family: str = "both") -> dict:
    families = list(FAMILIES) if family == "both" else [family]
    removed: list[str] = []
    for protocol in protocols:
        for fam in families:
            rules = await client.list_filter_rules()
            for rule in rules:
                if not is_managed(rule) or rule_family(rule) != fam:
                    continue
                if not matches_port(rule, protocol, ports, wan, family=fam):
                    continue
                rid = _text(rule.get(".id"))
                if rid:
                    await client.remove_filter_rule(rid, family=fam)
                    removed.append(f"{fam}/{rid}")
    left = await client.list_filter_rules()
    user_left = any(
        not is_managed(r) and matches_port(r, p, ports, wan, family=fam)
        for r in left for p in protocols for fam in families
    )
    return {"removed": removed, "user_rule_left": user_left}


async def set_lan_all(client: RouterOsClient, enable: bool) -> dict:
    sets = await interface_sets(client)
    lans, use_list = sets["lans"], sets["has_lan_list"]
    if not lans:
        raise ValueError("路由器上没有标记为 LAN 的接口，请先在接口列表里定义 LAN")

    changed: list[str] = []
    for fam in FAMILIES:
        for chain in CHAINS:
            rules = await client.list_filter_rules()
            matched = [r for r in rules
                       if rule_family(r) == fam
                       and _text(r.get("chain")) == chain
                       and matches_lan_all(r, lans, use_list, fam)]
            if enable:
                effective = effective_rule_ids(rules)
                if any(_rid(r) in effective for r in matched):
                    continue
                fields = {"chain": chain, "action": "accept", "comment": MANAGED_TAG}
                if use_list:
                    fields["in-interface-list"] = LAN_LIST_NAME
                else:
                    fields["in-interface"] = lans[0]
                await client.add_filter_rule(fields,
                                             place_before=first_blocker_id(rules, chain, fam),
                                             family=fam)
                changed.append(f"{fam}/{chain}")
            else:
                for rule in matched:
                    if is_managed(rule):
                        await client.remove_filter_rule(rule[".id"], family=fam)
                        changed.append(f"{fam}/{chain}")

    rules = await client.list_filter_rules()
    user_left = any(not is_managed(r) and matches_lan_all(r, lans, use_list, fam)
                    for r in rules for fam in FAMILIES)
    return {"changed": changed, "user_rule_left": user_left}


async def set_wan_all(client: RouterOsClient, enable: bool, wan: str, family: str) -> dict:
    sets = await interface_sets(client)
    if wan not in sets["wans"]:
        raise ValueError(f"{wan} 不是可用的 WAN 接口")
    families = list(FAMILIES) if family == "both" else [family]

    changed: list[str] = []
    for fam in families:
        for chain in CHAINS:
            rules = await client.list_filter_rules()
            matched = [r for r in rules
                       if rule_family(r) == fam
                       and _text(r.get("chain")) == chain
                       and matches_wan_all(r, wan, fam)]
            if enable:
                effective = effective_rule_ids(rules)
                if any(_rid(r) in effective for r in matched):
                    continue
                await client.add_filter_rule(
                    {"chain": chain, "action": "accept", "in-interface": wan,
                     "src-address": ALL_SRC[fam], "comment": MANAGED_TAG},
                    place_before=first_blocker_id(rules, chain, fam),
                    family=fam,
                )
                changed.append(f"{fam}/{chain}")
            else:
                for rule in matched:
                    if is_managed(rule):
                        await client.remove_filter_rule(rule[".id"], family=fam)
                        changed.append(f"{fam}/{chain}")

    rules = await client.list_filter_rules()
    user_left = any(not is_managed(r) and matches_wan_all(r, wan, fam)
                    for r in rules for fam in families)
    return {"changed": changed, "user_rule_left": user_left}
