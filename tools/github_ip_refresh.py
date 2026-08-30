#!/usr/bin/env python3
"""Dynamically refresh GitHub DNS Resource Records into docs/github_ip_records.csv.

为何需要：
    本机访问 github.com:443 偶发 DNS 实效 / 路由不可达，导致 push 失败。
    静态候选 IP 池（docs/github_ip_records.csv）可能过期，需动态补充最新 A 记录。

数据来源（按优先级，均可动态获得「DNS Resource Records」）：
    1. 系统解析器（nslookup / getent）——即使 github.com:443 被墙也能解析，首选；
    2. DNS-over-HTTPS（Cloudflare 1.1.1.1 / Google dns.google）——可达时使用；
    3. 人工从以下 3 个站点抄录（这些页面受 Cloudflare 挑战保护，无法自动抓取，
       故用 --manual 把你在页面上看到的 A 记录登记进来）：
         https://sites.ipaddress.com/github.com/
         https://sites.ipaddress.com/fastly.net/
         https://sites.ipaddress.com/assets-cdn.github.com/
   这 3 个站点是「当前 DNS Resource Records」的可人工核验权威来源；
   本工具把补充过程变成可复现、可审计的操作。

 产出：
     - 把新发现的 A 记录追加进 docs/github_ip_records.csv（去重，保留历史）；
     - 对 github.com 候选 IP 做**可达性 + TLS 证书合法性**双重探测（SNI=github.com）：
       仅「可达且签发合法 github.com 证书」的 IP 才能用于 hosts 覆盖（经验证，部分存活 IP
       如 140.82.112.4 证书主体不匹配，git/schannel 会 SEC_E_WRONG_PRINCIPAL 失败）；
     - 打印仅含证书合法+可达 IP 的 hosts 覆盖块；`--write-hosts` 可自动备份并写入
       （需以管理员/root 权限运行 opencode，否则仅备份并提示授权）。

 用法：
     py -3.11 tools/github_ip_refresh.py                 # Windows
     python3 tools/github_ip_refresh.py                  # macOS / Linux
     py -3.11 tools/github_ip_refresh.py --write-hosts   # 自动备份+写入证书合法IP(需提权)
     py -3.11 tools/github_ip_refresh.py --doh --manual github.com=20.205.243.166,...
"""
from __future__ import annotations

import csv
import json
import re
import socket
import ssl
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "github_ip_records.csv"

HOSTNAMES = [
    "github.com",
    "api.github.com",
    "gist.github.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
    "github.global.ssl.fastly.net",
    "assets-cdn.github.com",
    "fastly.net",
    "github.io",
]

FIELDS = ["domain", "record_type", "ip_address", "source", "last_verified_utc", "notes"]


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def resolve_nslookup(host: str) -> set[str]:
    ips: set[str] = set()
    try:
        out = subprocess.run(
            ["nslookup", host], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return ips
    for line in out.splitlines():
        m = re.search(r"Address:\s*(\d{1,3}(?:\.\d{1,3}){3})", line)
        if m and m.group(1) != "192.168.0.1":
            ips.add(m.group(1))
    return ips


def resolve_doh(host: str) -> set[str]:
    ips: set[str] = set()
    import urllib.request

    for url in (
        f"https://1.1.1.1/dns-query?name={host}&type=A",
        f"https://dns.google/resolve?name={host}&type=A",
    ):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
            for ans in data.get("Answer", []):
                if ans.get("type") == 1 and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ans.get("data", "")):
                    ips.add(ans["data"])
        except Exception:
            continue
    return ips


def load_existing() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))


# 探测逻辑统一走公共模块 tools/_gh_ip_probe.py（供 github_push.py 复用，避免双维护）
try:
    from _gh_ip_probe import probe_reachability, probe_tls
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _gh_ip_probe import probe_reachability, probe_tls


def _hosts_path() -> Path:
    import platform
    return Path("/etc/hosts") if platform.system() != "Windows" else \
        Path(r"C:\Windows\System32\drivers\etc\hosts")


def write_hosts(ip: str, host: str = "github.com") -> None:
    """备份 hosts 并覆盖/追加 `ip host` 行（铁律 #7：系统文件需提权+备份+留痕）。"""
    import platform
    hosts = _hosts_path()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = hosts.with_name(f"hosts_{ts}.bak")
    try:
        data = hosts.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"  [write-hosts] 读取 hosts 失败：{e}")
        return
    backup.write_text(data, encoding="utf-8")
    print(f"  [write-hosts] hosts 已备份至 {backup}")
    new_lines, replaced = [], False
    pat = re.compile(rf"^\s*[\d.]+[ \t]+\S*{re.escape(host)}\b")
    for ln in data.splitlines():
        if pat.match(ln):
            if not replaced:
                new_lines.append(f"{ip} {host}")
                replaced = True
            continue  # 丢弃旧行
        new_lines.append(ln)
    if not replaced:
        new_lines.append(f"{ip} {host}")
    try:
        hosts.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"  [write-hosts] 已写入 `{ip} {host}` 到 hosts")
    except PermissionError:
        print("  [write-hosts] PermissionError：写入被拒——请以管理员/root 权限运行 "
              "opencode 后重试（备份已留存，未改动 hosts）")
        return
    print("  [write-hosts] ⚠️ 系统文件已修改：按铁律 #7 需登记 "
          "13_安全审计台账.csv / 14_授权登记.csv（备份在 .backup/）")


def main(argv: list[str]) -> int:
    doh = "--doh" in argv
    manual: dict[str, list[str]] = {}
    if "--manual" in argv:
        for a in argv[argv.index("--manual") + 1:]:
            if "=" in a:
                h, ips = a.split("=", 1)
                manual[h.strip()] = [x.strip() for x in ips.split(",") if x.strip()]

    rows = load_existing()
    seen = {(r.get("domain"), r.get("ip_address")) for r in rows}
    added = 0
    today = utc_today()

    for host in HOSTNAMES:
        ips: set[str] = set()
        sys_resolved = resolve_nslookup(host)
        ips |= sys_resolved
        if doh:
            ips |= resolve_doh(host)
        if host in manual:
            ips |= set(manual[host])
        if not ips:
            continue
        source = "manual-ipaddress.com" if host in manual else (
            "system-resolver" if sys_resolved else "DoH"
        )
        for ip in sorted(ips):
            if (host, ip) not in seen:
                rows.append({
                    "domain": host,
                    "record_type": "A",
                    "ip_address": ip,
                    "source": source,
                    "last_verified_utc": today,
                    "notes": "动态补充(ipaddress.com/DoH/系统解析)",
                })
                seen.add((host, ip))
                added += 1

    has_bom = CSV_PATH.exists() and CSV_PATH.read_bytes()[:3] == b"\xef\xbb\xbf"
    with CSV_PATH.open("w", encoding="utf-8", newline="") as h:
        if has_bom:
            h.write("\ufeff")
        w = csv.DictWriter(h, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"[ok] 新增 {added} 条 DNS 记录；docs/github_ip_records.csv 现共 {len(rows)} 行")
    if manual:
        print("[ok] 已登记来自 ipaddress.com 的人工抄录记录")

    gh_ips = [r["ip_address"] for r in rows if r["domain"] == "github.com"]
    write_flag = "--write-hosts" in argv
    print("\n[探测] github.com 候选 IP：可达性 + TLS 证书合法性（SNI=github.com）：")
    good = []
    for ip in gh_ips[:8]:
        tcp, cert_ok, err = probe_tls(ip)
        if tcp and cert_ok:
            tag = "GOOD(可达+证书合法)"
            good.append(ip)
        elif tcp:
            tag = f"TCP可达但证书非法({err})"
        else:
            tag = f"不可达({err})"
        print(f"  {ip} -> TCP={tcp} 证书合法={cert_ok}  {tag}")

    if good:
        best = good[0]
        print("\n[恢复] 推荐 hosts 覆盖（仅证书合法且可达的 IP）：")
        print(f"  {best} github.com")
        if write_flag:
            print("  [write-hosts] 执行备份+写入：")
            write_hosts(best)
    else:
        print("\n[恢复] 无「可达+证书合法」IP；请等待 GitHub 恢复，或改从镜像(mirror)拉取：")
        print("  git pull mirror main   # 镜像与 GitHub 历史一致")

    print("\n[恢复] 也可使用 SSH-over-443 恢复脚本：")
    print("  bash tools/restore_github_push.sh --dry-run   # 预览")
    print("  bash tools/restore_github_push.sh             # 执行 SSH-over-443 恢复+push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
