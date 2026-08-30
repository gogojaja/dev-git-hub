#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github_push.py — GitHub 真实 IP 一键推送（固定动作，减少反复手动操作）

问题背景：
    本机访问 github.com:443 偶发 DNS 实效 / 路由不可达，普通 `git push origin`
    会反复失败。本脚本把「候选IP → 可达+TLS证书合法双重探测 → 绑定真实IP push」
    封装为一条命令，作为 GitHub push 的固定动作。

流程：
    1. （可选）解除本地代理污染（--keep-proxy 跳过）；
    2. 从 docs/github_ip_records.csv 读取 github.com 候选 IP（公共模块 _gh_ip_probe）；
    3. 逐个探测「可达性 + TLS 证书合法（SNI=github.com）」，命中首个合法 IP 即短路；
    4. `git -c http.curloptResolve=github.com:443:<IP> push origin <branch>` 推送；
    5. 成功 → PUSH_OK <IP>，退出 0；全部失败 → 诊断，退出 1；
    6. 留痕 台账/32_镜像同步记录.csv（remote=origin，URL 脱敏，SYNC 编号幂等）。

用法（跨平台）：
    py -3.11 tools/github_push.py                     # 默认推当前分支
    py -3.11 tools/github_push.py --branch main
    py -3.11 tools/github_push.py --dry-run           # 仅探测并打印将用 IP，不实际 push（回归测试）
    py -3.11 tools/github_push.py --keep-proxy        # 保留环境代理（默认解除）
    py -3.11 tools/github_push.py --timeout 5         # 单 IP TLS 探测超时秒（默认 8）

凭据（铁律 #3 A 级）：
    与 mirror_push.py 一致：GITHUB_TOKEN 经 .secrets/github_token 或环境变量提供，
    load_secret 自动装载，token 经 insteadOf 注入不持久化、绝不打印/落盘。
"""
from __future__ import annotations

import argparse
import csv
import datetime
import io
import os
import re
import subprocess
import sys

# ---- [M1 剥离增强] 支持 PROJECT_ROOT 环境变量（以目标仓库为工作根，默认/兜底自身根） ----
def _resolve_root(default_root):
    # 优先级：PROJECT_ROOT 环境变量 > 脚本自身根
    env = os.environ.get("PROJECT_ROOT") or os.environ.get("DPB_ROOT")
    if env and os.path.isdir(env):
        return env
    return default_root
ROOT_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = _resolve_root(ROOT_DEFAULT)

# ---- [M1 剥离增强] 支持 PROJECT_ROOT 环境变量（以目标仓库为工作根，默认/兜底自身根） ----
def _resolve_root(default_root):
    # 优先级：PROJECT_ROOT 环境变量 > 脚本自身根
    env = os.environ.get("PROJECT_ROOT") or os.environ.get("DPB_ROOT")
    if env and os.path.isdir(env):
        return env
    return default_root
LEDGER = os.path.join(ROOT, "台账", "32_镜像同步记录.csv")
# 铁律 #8：32 台账入库前对真实 IP 脱敏，避免 B 级门禁拦截与敏感泄露。
_IP_RE = re.compile(r'(\d{1,3}\.){3}\d{1,3}')


def _mask_ip(s):
    return _IP_RE.sub('xxx.xxx.xxx.xxx', s) if isinstance(s, str) else s

try:
    from _gh_ip_probe import probe_best_github_ip
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _gh_ip_probe import probe_best_github_ip


def _run(cmd, extra_env=None, timeout=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        from types import SimpleNamespace
        return SimpleNamespace(returncode=124, stdout="", stderr="[timeout %ss]" % timeout)


def _branch():
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return r.stdout.strip() or "main"


def _head():
    return _run(["git", "rev-parse", "HEAD"]).stdout.strip()


def _mask(url):
    return re.sub(r"://[^/@]+@", "://***@", url) if url else ""


def _load_secret():
    """跨平台装载 GitHub token 到环境变量（env > .secrets/github_token > Keychain）。"""
    try:
        import load_secret as ls
    except Exception:
        return None, None
    try:
        return ls.load("github_token")
    except Exception:
        return None, None


def _resolve_token():
    user = os.environ.get("GITHUB_USER")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        user, token = _load_secret()
    return user, token


def _next_seq():
    """幂等序号（P-005）：解析 SYNC-YYYYMMDD-NNN 取 max+1，避免并发/多端追加冲突。"""
    if not os.path.exists(LEDGER):
        return 1
    maxn = 0
    with io.open(LEDGER, "r", encoding="utf-8-sig") as f:
        for line in f:
            m = re.search(r"SYNC-\d{8}-(\d+)", line)
            if m:
                maxn = max(maxn, int(m.group(1)))
    return maxn + 1


def _append_ledger(row):
    header = ["同步编号", "同步时间", "源commit", "目标remote", "远程URL(脱敏)", "状态", "耗时秒", "说明"]
    new = not os.path.exists(LEDGER)
    with io.open(LEDGER, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow([_mask_ip(c) for c in row])


def _commit_ledger_via_agent_loop():
    """写账后若启用 agent-loop（根目录 .agent-loop-enabled 且非递归上下文），
    交由 agent_loop.py --commit-only 统一提交 32 台账，消除手动推送后的工作区脏残留。
    32 台账写入已脱敏，提交不触发 B 级门禁（铁律 #8）。"""
    if os.environ.get("AGENT_LOOP_ACTIVE") == "1":
        return
    if not os.path.exists(os.path.join(ROOT, ".agent-loop-enabled")):
        return
    agent_loop = os.path.join(ROOT, "tools", "agent_loop.py")
    if not os.path.exists(agent_loop):
        return
    env = dict(os.environ)
    env["AGENT_LOOP_ACTIVE"] = "1"
    try:
        r = subprocess.run([sys.executable, agent_loop, "--commit-only"], cwd=ROOT,
                           env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print("  (agent-loop 收口提交失败: %s)" % (r.stderr.strip() or r.stdout.strip() or "unknown"))
    except Exception as e:
        print("  (agent-loop 收口调用异常: %s)" % e)


def _clear_proxy():
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(k, None)


def _push_with_ip(ip, branch, token, user, timeout=40):
    """用指定 IP 绑定推送 origin（token 经 insteadOf 注入，不持久化）。返回 (ok, msg, elapsed)。"""
    extra_args = []
    if token:
        url = _run(["git", "remote", "get-url", "origin"]).stdout.strip()
        if "://" in url:
            proto, rest = url.split("://", 1)
            host = rest.split("/", 1)[0]
            auth = ("%s:" % user if user else "") + token + "@"
            instead = "%s://%s%s/" % (proto, auth, host)
            orig = "%s://%s/" % (proto, host)
            extra_args = ["-c", "url.%s.insteadOf=%s" % (instead, orig)]
    cmd = ["git", *extra_args,
           "-c", "http.curloptResolve=github.com:443:%s" % ip,
           "-c", "http.connectTimeout=12",
           "-c", "http.lowSpeedLimit=1000",
           "-c", "http.lowSpeedTime=30",
           "push", "origin", branch]
    start = datetime.datetime.now()
    res = _run(cmd, timeout=timeout)
    elapsed = (datetime.datetime.now() - start).total_seconds()
    ok = res.returncode == 0
    out = (res.stdout + res.stderr).strip()
    for s in (token, user):  # 铁律 #3 A 级：输出中抹除凭据，绝不回显/落盘
        if s:
            out = out.replace(s, "***")
    last = out.splitlines()[-1] if out else ""
    return ok, (last if last else ("成功" if ok else "失败")), elapsed


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    ap = argparse.ArgumentParser(description="GitHub 真实 IP 一键推送")
    ap.add_argument("--branch", default=None, help="推送分支（默认当前分支）")
    ap.add_argument("--keep-proxy", action="store_true", help="保留环境代理（默认解除）")
    ap.add_argument("--dry-run", action="store_true", help="仅探测并打印将用 IP，不实际 push")
    ap.add_argument("--timeout", type=int, default=8, help="单 IP TLS 探测超时秒（默认 8）")
    args = ap.parse_args(argv)

    if not args.keep_proxy:
        _clear_proxy()

    branch = args.branch or _branch()
    head = _head()

    print("[1/3] 探测 github.com 可达+证书合法 IP ...")
    ip = probe_best_github_ip(timeout=args.timeout)
    if not ip:
        print("[失败] 候选 IP 全部不可达或证书非法。请先运行：")
        print("       py -3.11 tools/github_ip_refresh.py --doh   # 动态刷新候选IP")
        return 1

    print("[2/3] 将使用 IP: %s （绑定 github.com:443）" % ip)
    url = _run(["git", "remote", "get-url", "origin"]).stdout.strip()

    if args.dry_run:
        print("[dry-run] 未实际推送。远端: %s，分支: %s，IP: %s" % (_mask(url), branch, ip))
        return 0

    user, token = _resolve_token()
    ok, msg, elapsed = _push_with_ip(ip, branch, token, user)
    now = datetime.datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    sid = "SYNC-%s-%03d" % (now.strftime("%Y%m%d"), _next_seq())

    if ok:
        if "up-to-date" in msg:
            print("[已同步] %s 已是最新（无新提交）" % branch)
            return 0
        _append_ledger([sid, now_str, head[:12], "origin", _mask(url),
                        "成功", "%.1f" % elapsed, "真实IP推送 PUSH_OK %s: %s" % (ip, msg)])
        print("PUSH_OK %s  (%.1fs)" % (ip, elapsed))
        _commit_ledger_via_agent_loop()
        return 0

    _append_ledger([sid, now_str, head[:12], "origin", _mask(url),
                    "失败", "%.1f" % elapsed, "真实IP推送失败 IP=%s: %s" % (ip, msg)])
    print("[失败] IP=%s 推送失败：%s" % (ip, msg))
    print("       提示：可尝试 `py -3.11 tools/github_ip_refresh.py --doh --write-hosts` 覆盖 hosts 后重试。")
    _commit_ledger_via_agent_loop()
    return 1


if __name__ == "__main__":
    sys.exit(main())