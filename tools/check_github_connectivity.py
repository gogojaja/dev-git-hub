#!/usr/bin/env python3
"""GitHub connectivity diagnosis and remediation.

This utility is designed for the exact failure pattern seen in this repo:
- DNS becomes stale or invalid, so GitHub is not reachable
- proxy/SOCKS settings break the connection path
- push fails before remote auth or repo availability can succeed

The script records known GitHub IP candidates, identifies likely failure modes,
recommends concrete remediation steps, and can be called from automation or from
CLI during a push failure.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "github_ip_records.csv"


def normalize_proxy_setting(value: str) -> str:
    """Normalize proxy strings like socks5h://localhost:64652 to host:port."""
    if not value:
        return ""
    cleaned = value.strip()
    for prefix in ("socks5h://", "socks5://", "http://", "https://"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    return cleaned.rstrip("/")


def read_known_github_ips() -> list[str]:
    """Read the repository's real GitHub IP references and return a stable list."""
    ips: set[str] = set()
    if not CSV_PATH.exists():
        return []

    with CSV_PATH.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ip = (row.get("ip_address") or "").strip()
            if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
                ips.add(ip)

    return sorted(ips, key=lambda ip: [int(part) for part in ip.split(".")])


def detect_failure_mode(log_text: str) -> str:
    """Classify a git push failure into the most likely root cause."""
    text = (log_text or "").lower()

    if any(token in text for token in (
        "connection failed",
        "socks error",
        "could not connect",
        "recv failure",
        "connection reset by peer",
        "connection closed by unknown port",
        "connection closed by",
        "connection closed by 20.205.243.166 port 443",
    )):
        return "proxy_or_network_block"

    if any(token in text for token in (
        "could not resolve host",
        "temporary failure in name resolution",
        "name or service not known",
        "no address associated with hostname",
        "failed to connect to github.com",
        "failed to connect to github.com port 443",
    )):
        return "dns_invalid"

    if any(token in text for token in (
        "permission to",
        "repository not found",
        "access denied",
        "denied to",
        "401",
        "403",
        "authentication failed",
        "could not read from remote repository",
        "remote: error: access denied",
    )):
        return "auth_or_permission"

    if any(token in text for token in (
        "timed out",
        "network is unreachable",
        "no route to host",
    )):
        return "network_unreachable"

    if "ssh: connect to host github.com port 22" in text:
        return "ssh_port_block"

    return "unknown"


def get_remediation_steps(mode: str) -> list[str]:
    """Return actionable recovery steps for the diagnosed failure mode."""
    if mode == "dns_invalid":
        return [
            "git remote -v",
            "python3 tools/github_ip_refresh.py  # 动态补充 DNS Resource Records(系统解析器/DoH/ipaddress.com)",
            "nslookup github.com 8.8.8.8 || getent hosts github.com || ping -c 1 github.com",
            "cat docs/github_ip_records.csv | head -n 20",
            "curl -I --connect-timeout 8 https://github.com",
            "sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder 2>/dev/null || true",
            "ipconfig /flushdns 2>/dev/null || true",
            "git config --global --unset-all http.proxy || true",
            "git config --global --unset-all https.proxy || true",
            "git config --global --unset-all all.proxy || true",
            "python3 tools/check_github_connectivity.py --list-ips",
            "git push origin HEAD",
        ]

    if mode == "proxy_or_network_block":
        return [
            "git remote -v",
            "env | grep -Ei 'http|https|proxy|socks' | sort",
            "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy",
            "git config --global --unset-all http.proxy || true",
            "git config --global --unset-all https.proxy || true",
            "git config --global --unset-all all.proxy || true",
            "curl -I --connect-timeout 8 https://github.com",
            "curl -I --connect-timeout 8 --resolve github.com:443:20.205.243.166 https://github.com",
            "ssh -T -o StrictHostKeyChecking=no -p 443 git@ssh.github.com",
            "git remote set-url origin ssh://git@ssh.github.com:443/<user>/<repo>.git",
            "python3 tools/check_github_connectivity.py --list-ips",
            "git ls-remote origin HEAD",
            "git push origin HEAD",
        ]

    if mode == "auth_or_permission":
        return [
            "git remote -v",
            "git config --get remote.origin.url",
            "ssh -T git@github.com",
            "gh auth status || true",
            "git remote set-url origin https://github.com/<user>/<repo>.git",
            "git push origin HEAD",
        ]

    if mode == "ssh_port_block":
        return [
            "ssh -T -v git@github.com",
            "ssh -o 'ProxyCommand=nc -X connect -x localhost:PORT %h %p' git@github.com",
            "git remote -v",
            "git remote set-url origin git@github.com:<user>/<repo>.git",
            "git push origin HEAD",
        ]

    if mode == "network_unreachable":
        return [
            "ping -c 1 github.com",
            "curl -I --connect-timeout 8 https://github.com",
            "nslookup github.com 8.8.8.8 || getent hosts github.com || ping -c 1 github.com",
            "test network connectivity and VPN/proxy status",
            "git push origin HEAD",
        ]

    return [
        "git remote -v",
        "env | grep -Ei 'http|https|proxy|socks' | sort",
        "curl -I --connect-timeout 8 https://github.com",
        "python3 tools/check_github_connectivity.py --list-ips",
        "git push origin HEAD",
    ]


def describe_known_ips() -> str:
    ips = read_known_github_ips()
    if not ips:
        return "No known GitHub IP list found in docs/github_ip_records.csv"
    first = ips[:12]
    return ", ".join(first)


def main(argv: list[str]) -> int:
    if "--list-ips" in argv:
        ips = read_known_github_ips()
        if ips:
            print("\n".join(ips))
            return 0
        print("No GitHub IPs recorded.")
        return 1

    if "--check" in argv:
        env_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY") or ""
        print("GitHub connectivity diagnosis")
        print(f"Known IPs: {describe_known_ips()}")
        if env_proxy:
            print(f"Detected proxy: {normalize_proxy_setting(env_proxy)}")
        else:
            print("No explicit HTTP proxy detected in environment.")
        return 0

    if "--from-push-output" in argv:
        idx = argv.index("--from-push-output") + 1
        if idx >= len(argv):
            print("Missing file path after --from-push-output", file=sys.stderr)
            return 2
        path = Path(argv[idx])
        if not path.exists():
            print(f"File does not exist: {path}", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8", errors="replace")
        mode = detect_failure_mode(text)
        print(f"failure_mode={mode}")
        print(f"known_ips={describe_known_ips()}")
        for i, step in enumerate(get_remediation_steps(mode), start=1):
            print(f"{i}. {step}")
        return 0

    if len(argv) > 1:
        text = " ".join(argv[1:])
        mode = detect_failure_mode(text)
        print(f"failure_mode={mode}")
        print(f"known_ips={describe_known_ips()}")
        for i, step in enumerate(get_remediation_steps(mode), start=1):
            print(f"{i}. {step}")
        return 0

    # default CLI usage with environment snapshot
    proxies = {
        key: normalize_proxy_setting(value)
        for key, value in os.environ.items()
        if key.lower().endswith("proxy") and value
    }
    print("GitHub connectivity diagnosis")
    print(f"Known GitHub IPs: {describe_known_ips()}")
    if proxies:
        print("Proxies detected:")
        for key, value in proxies.items():
            print(f"  - {key}={value}")
    else:
        print("No proxy variables detected in environment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
