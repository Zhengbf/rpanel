"""一键放通：把常见的防火墙放通需求封装成场景。

约定（与前端页面对齐）：
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


def _text(value) -> str:
    return str(value or "").strip()


def _blank(rule: dict, *keys: str) -> bool:
    return all(not _text(rule.get(k)) for k in keys)


def is_managed(rule: dict) -> bool:
    return MANAGED_TAG in _text(rule.get("comment"))


def first_blocker_id(rules: list[dict], chain: str) -> str | None:
    for rule in rules:
        if _text(rule.get("chain")) == chain and _text(rule.get("action")) in BLOCK_ACTIONS:
            return rule.get(".id")
    return None


def effective_rule_ids(rules: list[dict]) -> set[str]:
    """accept 规则只有在所属链的第一条 drop/reject 之前才真正生效。"""
    blocker_index = {}
    for chain in CHAINS:
        for i, rule in enumerate(rules):
            if _text(rule.get("chain")) == chain and _text(rule.get("action")) in BLOCK_ACTIONS:
                blocker_index[chain] = i
                break

    effective: set[str] = set()
    for i, rule in enumerate(rules):
        if _text(rule.get("action")) != "accept":
            continue
        chain = _text(rule.get("chain"))
        if chain not in CHAINS:
            continue
        idx = blocker_index.get(chain)
        rid = rule.get(".id")
        if rid and (idx is None or i < idx):
            effective.add(rid)
    return effective


def matches_port(rule: dict, protocol: str, ports: str, wan: str,
                 chain: str | None = None) -> bool:
    """chain 传了就只比对该链：input 和 forward 是两条独立规则，不能互相顶替。"""
    return (
        _text(rule.get("action")) == "accept"
        and _text(rule.get("chain")) in CHAINS
        and (chain is None or _text(rule.get("chain")) == chain)
        and _text(rule.get("protocol")) == protocol
        and _text(rule.get("dst-port")).replace(" ", "") == ports.replace(" ", "")
        and _text(rule.get("in-interface")) == wan
    )


def matches_lan_all(rule: dict, lan_names: list[str], use_list: bool) -> bool:
    if _text(rule.get("action")) != "accept" or _text(rule.get("chain")) not in CHAINS:
        return False
    # 场景规则是"全放通"，任何额外匹配条件都说明不是同一条场景
    if not _blank(rule, "protocol", "dst-port", "src-address", "dst-address",
                  "src-address-list", "dst-address-list"):
        return False
    if use_list:
        return _text(rule.get("in-interface-list")).upper() == LAN_LIST_NAME
    return _text(rule.get("in-interface")) in lan_names


def matches_wan_all(rule: dict, wan: str, family: str) -> bool:
    if _text(rule.get("action")) != "accept" or _text(rule.get("chain")) not in CHAINS:
        return False
    if _text(rule.get("in-interface")) != wan:
        return False
    if not _blank(rule, "protocol", "dst-port"):
        return False
    return _text(rule.get("src-address")) == ("0.0.0.0/0" if family == "v4" else "::/0")


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


def _serialize(rule: dict, effective: set[str]) -> dict:
    return {
        "id": _text(rule.get(".id")),
        "chain": _text(rule.get("chain")),
        "action": _text(rule.get("action")),
        "protocol": _text(rule.get("protocol")),
        "dst_port": _text(rule.get("dst-port")),
        "in_interface": _text(rule.get("in-interface")),
        "in_interface_list": _text(rule.get("in-interface-list")),
        "src_address": _text(rule.get("src-address")),
        "comment": _text(rule.get("comment")),
        "managed": is_managed(rule),
        "effective": _text(rule.get(".id")) in effective,
    }


async def build_status(client: RouterOsClient) -> dict:
    rules = await client.list_filter_rules()
    effective = effective_rule_ids(rules)
    sets = await interface_sets(client)
    wans, lans = sets["wans"], sets["lans"]

    # 已存在的端口放通（含用户自建），按 协议+端口+WAN 归组
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
            "managed": False, "user_rule": False, "effective": False, "chains": [],
        })
        entry["managed"] = entry["managed"] or is_managed(rule)
        entry["user_rule"] = entry["user_rule"] or not is_managed(rule)
        entry["effective"] = entry["effective"] or (_text(rule.get(".id")) in effective)
        chain = _text(rule.get("chain"))
        if chain and chain not in entry["chains"]:
            entry["chains"].append(chain)

    def scene_state(predicate) -> dict:
        matched = [r for r in rules if predicate(r)]
        return {
            "allowed": any(_text(r.get(".id")) in effective for r in matched),
            "managed": any(is_managed(r) for r in matched),
            "user_rule": any(not is_managed(r) for r in matched),
            "chains": sorted({_text(r.get("chain")) for r in matched
                              if _text(r.get("chain")) in CHAINS}),
        }

    use_lan_list = sets["has_lan_list"]
    wan_all = []
    for wan in wans:
        wan_all.append({
            "wan": wan,
            "v4": scene_state(lambda r, w=wan: matches_wan_all(r, w, "v4")),
            "v6": scene_state(lambda r, w=wan: matches_wan_all(r, w, "v6")),
        })

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
            "lan_all": scene_state(lambda r: matches_lan_all(r, lans, use_lan_list)),
            "wan_all": wan_all,
        },
    }


async def allow_port(client: RouterOsClient, protocols: list[str], ports: str,
                     wan: str) -> dict:
    sets = await interface_sets(client)
    if wan not in sets["wans"]:
        raise ValueError(f"{wan} 不是可用的 WAN 接口")
    created: list[str] = []
    existed: list[str] = []
    for protocol in protocols:
        for chain in CHAINS:
            rules = await client.list_filter_rules()
            effective = effective_rule_ids(rules)
            if any(matches_port(r, protocol, ports, wan, chain)
                   and _text(r.get(".id")) in effective
                   for r in rules):
                existed.append(f"{protocol}/{chain}")
                continue
            await client.add_filter_rule(
                {"chain": chain, "action": "accept", "protocol": protocol,
                 "dst-port": ports, "in-interface": wan, "comment": MANAGED_TAG},
                place_before=first_blocker_id(rules, chain),
            )
            created.append(f"{protocol}/{chain}")
    return {"created": created, "existed": existed, "user_rule_left": False}


async def revoke_port(client: RouterOsClient, protocols: list[str], ports: str,
                      wan: str) -> dict:
    removed: list[str] = []
    for protocol in protocols:
        rules = await client.list_filter_rules()
        for rule in rules:
            if is_managed(rule) and matches_port(rule, protocol, ports, wan):
                rid = rule.get(".id")
                if rid:
                    await client.remove_filter_rule(rid)
                    removed.append(rid)
    left = await client.list_filter_rules()
    user_left = any(matches_port(r, p, ports, wan) for r in left for p in protocols
                    if not is_managed(r))
    return {"removed": removed, "user_rule_left": user_left}


async def set_lan_all(client: RouterOsClient, enable: bool) -> dict:
    sets = await interface_sets(client)
    lans, use_list = sets["lans"], sets["has_lan_list"]
    if not lans:
        raise ValueError("路由器上没有标记为 LAN 的接口，请先在接口列表里定义 LAN")

    changed: list[str] = []
    for chain in CHAINS:
        rules = await client.list_filter_rules()
        matched = [r for r in rules
                   if matches_lan_all(r, lans, use_list) and _text(r.get("chain")) == chain]
        if enable:
            if any(_text(r.get(".id")) in effective_rule_ids(rules) for r in matched):
                continue
            fields = {"chain": chain, "action": "accept", "comment": MANAGED_TAG}
            if use_list:
                fields["in-interface-list"] = LAN_LIST_NAME
            else:
                fields["in-interface"] = lans[0]
            await client.add_filter_rule(fields, place_before=first_blocker_id(rules, chain))
            changed.append(chain)
        else:
            for rule in matched:
                if is_managed(rule):
                    await client.remove_filter_rule(rule[".id"])
                    changed.append(chain)

    rules = await client.list_filter_rules()
    user_left = any(not is_managed(r) and matches_lan_all(r, lans, use_list) for r in rules)
    return {"changed": changed, "user_rule_left": user_left}


async def set_wan_all(client: RouterOsClient, enable: bool, wan: str, family: str) -> dict:
    sets = await interface_sets(client)
    if wan not in sets["wans"]:
        raise ValueError(f"{wan} 不是可用的 WAN 接口")
    families = ["v4", "v6"] if family == "both" else [family]

    changed: list[str] = []
    for fam in families:
        for chain in CHAINS:
            rules = await client.list_filter_rules()
            matched = [r for r in rules
                       if matches_wan_all(r, wan, fam) and _text(r.get("chain")) == chain]
            if enable:
                if any(_text(r.get(".id")) in effective_rule_ids(rules) for r in matched):
                    continue
                await client.add_filter_rule(
                    {"chain": chain, "action": "accept", "in-interface": wan,
                     "src-address": "0.0.0.0/0" if fam == "v4" else "::/0",
                     "comment": MANAGED_TAG},
                    place_before=first_blocker_id(rules, chain),
                )
                changed.append(f"{fam}/{chain}")
            else:
                for rule in matched:
                    if is_managed(rule):
                        await client.remove_filter_rule(rule[".id"])
                        changed.append(f"{fam}/{chain}")

    rules = await client.list_filter_rules()
    user_left = any(not is_managed(r) and matches_wan_all(r, wan, fam)
                    for r in rules for fam in families)
    return {"changed": changed, "user_rule_left": user_left}
