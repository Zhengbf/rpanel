"""
RouterOS 输出健壮解析。

基于 RouterOS 7.24.4 实测输出校准：
- 连接跟踪字段为独立的 orig-bytes / repl-bytes，数字带空格千位分隔
- CLI 中 src-address 与 src-port 是分离字段
- /system/resource/print 等输出无编号行，纯 key=value（v2 修复）
"""
from __future__ import annotations
import re
from app.adapters.ros.base import ConnectionEntry

_SPACED_NUMERIC_FIELDS = {
    "orig-bytes", "repl-bytes", "reply-bytes", "bytes",
    "orig-packets", "repl-packets", "reply-packets",
    "orig-fasttrack-bytes", "repl-fasttrack-bytes",
    "orig-fasttrack-packets", "repl-fasttrack-packets",
}

_TOKEN_KV = re.compile(r"^([a-zA-Z][a-zA-Z0-9\-]*)=(.*)$")
_NEW_ENTRY = re.compile(r"^\s{0,3}\d+\s")
_THREE_DIGITS = re.compile(r"^\d{3}$")


def parse_kv_tokens(line: str) -> list[tuple[str, str]]:
    tokens = line.split()
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        m = _TOKEN_KV.match(t)
        if m:
            key, val = m.group(1), m.group(2)
            if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            i += 1
            if key in _SPACED_NUMERIC_FIELDS and re.fullmatch(r"\d{1,3}", val):
                while i < len(tokens) and _THREE_DIGITS.match(tokens[i]):
                    val += tokens[i]
                    i += 1
            out.append((key, val))
        else:
            i += 1
    return out


def parse_detail_blocks(output: str) -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    saw_numbered = False
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith(("Flags:", "Columns:", ";;;")):
            continue
        if _NEW_ENTRY.match(raw_line):
            saw_numbered = True
            if current:
                entries.append(current)
            current = {}
            tokens = raw_line.split()
            flags: list[str] = []
            started = False
            for t in tokens[1:]:
                if "=" in t:
                    started = True
                elif not started:
                    flags.append(t)
            for k, v in parse_kv_tokens(" ".join(tokens[1:])):
                current[k] = v
            if flags:
                current["_flags"] = "".join(flags)
        else:
            kvs = parse_kv_tokens(raw_line)
            if not kvs:
                continue
            # 无编号输出（如 /system/resource/print）：
            # 若当前无条目或行含 "key:" 风格的顶部字段，作为新条目
            if current is None:
                current = {}
            for k, v in kvs:
                current[k] = v
    if current:
        entries.append(current)
    if not saw_numbered and not entries:
        # 兜底：把 "key: value" 风格解析成一个条目
        entry: dict = {}
        for raw_line in output.splitlines():
            m = re.match(r"^\s*([a-zA-Z][a-zA-Z0-9\-\s]*?):\s*(.*)$", raw_line)
            if m:
                key = m.group(1).strip().replace(" ", "-")
                entry[key] = m.group(2).strip()
        if entry:
            entries.append(entry)
    return entries


def parse_bytes_value(raw: str | int | float | None) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw).strip()
    if not s:
        return 0
    if " " in s and s.replace(" ", "").isdigit():
        return int(s.replace(" ", ""))
    try:
        return int(s)
    except ValueError:
        return 0


_SIZE_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "K": 1024, "M": 1024**2, "G": 1024**3}


def parse_human_size(raw: str | None) -> int:
    if not raw:
        return 0
    s = str(raw).strip()
    m = re.match(r"^([\d.]+)\s*([A-Za-z]+)$", s)
    if not m:
        try:
            return int(float(s))
        except ValueError:
            return 0
    num, unit = m.group(1), m.group(2)
    factor = _SIZE_UNITS.get(unit)
    if factor is None:
        try:
            return int(float(num))
        except ValueError:
            return 0
    return int(float(num) * factor)


def parse_percent(raw: str | int | None) -> float:
    if raw is None:
        return 0.0
    s = str(raw).strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_uptime(raw: str | None) -> int:
    parts = re.findall(r"(\d+)([wdhms])", raw or "")
    if not parts:
        return 0
    mult = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * mult[u] for n, u in parts)


def parse_host_port(raw: str | None, port_fallback: str | int | None = None) -> tuple[str, int | None]:
    if not raw:
        return "", None
    s = str(raw).strip()
    if s.count(":") == 1 and "." in s:
        host, _, p = s.partition(":")
        try:
            return host, int(p)
        except ValueError:
            return host, None
    if port_fallback is not None:
        try:
            return s, int(port_fallback)
        except (ValueError, TypeError):
            return s, None
    return s, None


def parse_connection_bytes(entry: dict) -> tuple[int, int]:
    orig_raw = entry.get("orig-bytes")
    repl_raw = entry.get("repl-bytes", entry.get("reply-bytes"))
    if orig_raw is not None or repl_raw is not None:
        return parse_bytes_value(orig_raw), parse_bytes_value(repl_raw)
    raw = entry.get("bytes")
    if raw is None:
        return 0, 0
    parts = str(raw).strip().split()
    if len(parts) >= 2:
        return parse_bytes_value(parts[0]), parse_bytes_value(parts[1])
    return parse_bytes_value(str(raw)), 0


_RATE_UNITS = {"bps": 1, "kbps": 1e3, "mbps": 1e6, "gbps": 1e9}


def parse_rate_bps(raw: str | int | float | None) -> float:
    """RouterOS rate 字段：REST 返回纯数字(bit/s)，SSH 返回 '110.2kbps'。统一为 bit/s。"""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().lower()
    if not s:
        return 0.0
    for unit in ("gbps", "mbps", "kbps", "bps"):
        if s.endswith(unit):
            num = s[:-len(unit)].strip()
            try:
                return float(num) * _RATE_UNITS[unit]
            except ValueError:
                return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_fasttrack_bytes(raw: dict) -> int:
    """fasttrack 独立计数（部分 RouterOS 版本把快速转发流量记在这里）。"""
    o = parse_bytes_value(raw.get("orig-fasttrack-bytes"))
    r = parse_bytes_value(raw.get("repl-fasttrack-bytes"))
    return o + r


def to_connection_entry(raw: dict) -> ConnectionEntry:
    orig, repl = parse_connection_bytes(raw)
    orig += parse_bytes_value(raw.get("orig-fasttrack-bytes"))
    repl += parse_bytes_value(raw.get("repl-fasttrack-bytes"))
    src_ip, src_port = parse_host_port(raw.get("src-address"), raw.get("src-port"))
    dst_ip, dst_port = parse_host_port(raw.get("dst-address"), raw.get("dst-port"))
    reply_src_ip, reply_src_port = parse_host_port(raw.get("reply-src-address"), raw.get("reply-src-port"))
    reply_dst_ip, reply_dst_port = parse_host_port(raw.get("reply-dst-address"), raw.get("reply-dst-port"))
    return ConnectionEntry(
        id=raw.get(".id", raw.get("id", "")),
        protocol=raw.get("protocol", ""),
        src_address=raw.get("src-address", ""),
        dst_address=raw.get("dst-address", ""),
        src_ip=src_ip,
        src_port=src_port,
        dst_ip=dst_ip,
        dst_port=dst_port,
        state=raw.get("tcp-state", raw.get("state", raw.get("status", ""))),
        reply_src_ip=reply_src_ip,
        reply_src_port=reply_src_port,
        reply_dst_ip=reply_dst_ip,
        reply_dst_port=reply_dst_port,
        orig_rate=parse_rate_bps(raw.get("orig-rate")) / 8,   # bit/s -> byte/s
        repl_rate=parse_rate_bps(raw.get("repl-rate")) / 8,
        fasttrack_bytes=parse_fasttrack_bytes(raw),
        orig_bytes=orig,
        reply_bytes=repl,
        total_bytes=orig + repl,
        connection_mark=raw.get("connection-mark", ""),
        timeout=raw.get("timeout", ""),
    )


def normalize_host(raw: str) -> str:
    """去掉 scheme 前缀、路径和空格，返回纯 IP/主机名。"""
    s = (raw or "").strip()
    for prefix in ("https://", "http://"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    s = s.split("/")[0].strip()
    return s
