#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub IP 探测公共模块（供 github_ip_refresh.py / github_push.py 复用，避免双维护）。

提供：
    probe_tls(ip, host, timeout)      -> (tcp_ok, cert_ok, err)  跨平台 TLS 证书合法探测（SNI=host）
    probe_reachability(ip, host)      -> http_code / ERR          curl 可达性探测
    read_github_ips(max_candidates)   -> list[str]                从 docs/github_ip_records.csv 读 github.com 候选 IP
    probe_best_github_ip(...)         -> ip | None                返回首个「可达+证书合法」的 github.com IP
"""
from __future__ import annotations

import os
import socket
import ssl
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "github_ip_records.csv"


def probe_tls(ip: str, host: str = "github.com", timeout: int = 8):
    """返回 (tcp_ok, cert_ok, err)。跨平台（Python ssl 用各系统 CA 库）。"""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((ip, 443), timeout=timeout) as sock:
            try:
                with ctx.wrap_socket(sock, server_hostname=host):
                    pass
                return True, True, ""
            except ssl.SSLError as e:
                return True, False, "SSL:%s" % e
            except Exception as e:  # 其它 TLS 层异常
                return True, False, "TLS:%s" % e
    except (socket.timeout, OSError) as e:
        return False, False, "TCP:%s" % e


def probe_reachability(ip: str, host: str = "github.com") -> str:
    """curl 可达性探测，返回 HTTP 状态码字符串或 ERR。跨平台：Windows 用 curl.exe，其它平台用 curl。"""
    curl = "curl.exe" if os.name == "nt" else "curl"
    try:
        r = subprocess.run(
            [curl, "-s", "-o", "NUL", "-w", "%{http_code}",
             "--connect-timeout", "6", "--resolve", "%s:443:%s" % (host, ip),
             "https://%s" % host],
            capture_output=True, text=True, timeout=12,
        )
        return r.stdout.strip() or "ERR"
    except Exception:
        return "ERR"


def read_github_ips(max_candidates: int = 12) -> list:
    """从 docs/github_ip_records.csv 读 github.com 域候选 IP（去重，保留记录顺序）。"""
    ips = []
    seen = set()
    if not CSV_PATH.exists():
        return ips
    with CSV_PATH.open(encoding="utf-8-sig") as h:
        import csv
        for row in csv.DictReader(h):
            if (row.get("domain") or "").strip() != "github.com":
                continue
            ip = (row.get("ip_address") or "").strip()
            if ip and ip not in seen:
                seen.add(ip)
                ips.append(ip)
    return ips[:max_candidates]


def probe_best_github_ip(max_candidates: int = 8, timeout: int = 8):
    """返回首个「可达+证书合法」的 github.com IP；无则返回 None（命中即短路，不串行探测全部）。

    双重探测：TLS 证书合法（SNI=github.com）仅为前提，还必须 curl 实际 HTTP 请求成功
    （返回真实状态码 2xx/3xx/4xx）——仅 TCP/TLS 握手成功但路由会丢弃真实请求的 IP
    视为不可用（如 20.205.243.166 曾出现 TLS 可握手、push 却 Connection reset）。
    """
    for ip in read_github_ips(max_candidates):
        tcp, cert_ok, _ = probe_tls(ip, timeout=timeout)
        if not (tcp and cert_ok):
            continue
        code = probe_reachability(ip)
        if code in ("ERR", "000", ""):
            continue
        try:
            if 200 <= int(code) < 500:
                return ip
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    best = probe_best_github_ip()
    if best:
        print("GOOD %s" % best)
    else:
        print("NO_GOOD_IP")