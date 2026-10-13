from app.adapters.ros.parser import (
    parse_kv_tokens, parse_detail_blocks, parse_bytes_value,
    parse_human_size, parse_percent, parse_uptime,
    parse_host_port, parse_connection_bytes, to_connection_entry,
    parse_rate_bps, parse_fasttrack_bytes,
)

SAMPLE_CONN_LINE = (
    "timeout=29s orig-packets=50 575 orig-bytes=9 744 961 "
    "orig-fasttrack-packets=0 orig-fasttrack-bytes=0 repl-packets=0 "
    "repl-bytes=0 repl-fasttrack-packets=0 repl-fasttrack-bytes=0 orig-rate=110.2kbps"
)

SAMPLE_DETAIL = """Flags: S - SEEN-REPLY; A - ASSURED; C - CONFIRMED; s - SRCNAT; d - DSTNAT
  3 SACs  protocol=tcp src-address=192.168.88.30 src-port=37532 dst-address=203.0.113.7 dst-port=7201 reply-src-address=203.0.113.7 reply-src-port=7201 reply-dst-address=198.51.100.23 reply-dst-port=37532
          tcp-state=established timeout=23h59m23s orig-packets=13 625 orig-bytes=1 029 441 orig-fasttrack-packets=0 orig-fasttrack-bytes=0 repl-packets=10 366 repl-bytes=781 786 repl-fasttrack-packets=0
          repl-fasttrack-bytes=0 orig-rate=0bps repl-rate=0bps

  1   C   protocol=udp src-address=192.168.88.11 src-port=44974 dst-address=192.168.88.50 dst-port=54326 reply-src-address=192.168.88.50 reply-src-port=54326 reply-dst-address=192.168.88.11 reply-dst-port=44974
          timeout=29s orig-packets=50 575 orig-bytes=9 744 961 orig-fasttrack-packets=0 orig-fasttrack-bytes=0 repl-packets=0 repl-bytes=0 repl-fasttrack-packets=0 repl-fasttrack-bytes=0 orig-rate=110.2kbps
          repl-rate=0bps
"""


def test_spaced_thousands_merge():
    kvs = dict(parse_kv_tokens(SAMPLE_CONN_LINE))
    assert kvs["orig-bytes"] == "9744961"
    assert kvs["orig-packets"] == "50575"
    assert kvs["repl-bytes"] == "0"
    assert kvs["orig-fasttrack-packets"] == "0"
    assert kvs["orig-rate"] == "110.2kbps"


def test_bytes_value_variants():
    assert parse_bytes_value(12345) == 12345
    assert parse_bytes_value("12345") == 12345
    assert parse_bytes_value("9 744 961") == 9744961
    assert parse_bytes_value(None) == 0
    assert parse_bytes_value("") == 0
    assert parse_bytes_value("abc") == 0


def test_detail_blocks_count_and_flags():
    entries = parse_detail_blocks(SAMPLE_DETAIL)
    assert len(entries) == 2
    e3 = next(e for e in entries if e.get("src-address") == "192.168.88.30"
              and e.get("src-port") == "37532")
    assert e3["protocol"] == "tcp"
    assert e3["tcp-state"] == "established"
    assert "SAC" in e3.get("_flags", "")


def test_connection_entry_directions():
    entries = parse_detail_blocks(SAMPLE_DETAIL)
    e = to_connection_entry(entries[0])
    assert e.src_ip == "192.168.88.30"
    assert e.src_port == 37532
    assert e.dst_ip == "203.0.113.7"
    assert e.orig_bytes == 1029441
    assert e.reply_bytes == 781786
    assert e.total_bytes == 1029441 + 781786
    assert e.state == "established"


def test_connection_entry_zero_reply():
    entries = parse_detail_blocks(SAMPLE_DETAIL)
    e = to_connection_entry(entries[1])
    assert e.src_ip == "192.168.88.11"
    assert e.src_port == 44974
    assert e.orig_bytes == 9744961
    assert e.reply_bytes == 0


def test_combined_bytes_field():
    assert parse_connection_bytes({"bytes": "100 200"}) == (100, 200)
    assert parse_connection_bytes({"bytes": "500"}) == (500, 0)


def test_human_size():
    assert parse_human_size("1743.4MiB") == int(1743.4 * 1024 * 1024)
    assert parse_human_size("2048.0MiB") == 2 * 1024**3
    assert parse_human_size("512B") == 512
    assert parse_human_size("12345") == 12345


def test_percent():
    assert parse_percent("0%") == 0.0
    assert parse_percent("37%") == 37.0
    assert parse_percent(12) == 12.0


def test_uptime():
    assert parse_uptime("2w3d48m47s") == 2 * 604800 + 3 * 86400 + 48 * 60 + 47
    assert parse_uptime("5s") == 5
    assert parse_uptime("") == 0


def test_host_port():
    assert parse_host_port("192.168.88.11:44974") == ("192.168.88.11", 44974)
    assert parse_host_port("192.168.88.11", "44974") == ("192.168.88.11", 44974)
    assert parse_host_port(None) == ("", None)


# --- NAT 改写场景：内网主机出现在 reply-src-address（端口转发/入站连接）---


def test_connection_entry_reads_reply_addresses():
    raw = {
        ".id": "*A1",
        "protocol": "udp",
        "src-address": "203.0.113.9", "src-port": "24703",
        "dst-address": "198.51.100.23", "dst-port": "64254",
        "reply-src-address": "192.168.88.3", "reply-src-port": "64254",
        "reply-dst-address": "203.0.113.9", "reply-dst-port": "24703",
        "orig-bytes": "1000", "repl-bytes": "2000",
        "orig-rate": "264928", "repl-rate": "0",
    }
    e = to_connection_entry(raw)
    assert e.src_ip == "203.0.113.9"
    assert e.reply_src_ip == "192.168.88.3"
    assert e.reply_src_port == 64254
    assert e.reply_dst_ip == "203.0.113.9"
    # rate 字段是 bit/s，内部换算为 byte/s
    assert abs(e.orig_rate - 264928 / 8) < 0.01
    assert e.repl_rate == 0.0


def test_parse_rate_bps_formats():
    assert parse_rate_bps("264928") == 264928
    assert parse_rate_bps(1000) == 1000
    assert abs(parse_rate_bps("110.2kbps") - 110200) < 0.1
    assert abs(parse_rate_bps("2.4Mbps") - 2_400_000) < 1
    assert parse_rate_bps(None) == 0
    assert parse_rate_bps("") == 0


def test_fasttrack_bytes_summed_and_total():
    raw = {
        ".id": "*B1",
        "protocol": "tcp",
        "src-address": "192.168.88.11", "src-port": "1",
        "dst-address": "1.1.1.1", "dst-port": "443",
        "orig-bytes": "100", "repl-bytes": "200",
        "orig-fasttrack-bytes": "1000", "repl-fasttrack-bytes": "2000",
    }
    assert parse_fasttrack_bytes(raw) == 3000
    e = to_connection_entry(raw)
    assert e.orig_bytes == 1100
    assert e.reply_bytes == 2200
    assert e.total_bytes == 3300
