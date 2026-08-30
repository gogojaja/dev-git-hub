#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mirror_push.py — 国内镜像同步（地缘风险对冲）双推工具

策略：每次提交同时推送 origin(GitHub) + mirror(Gitee) 等多个 remote。
单目标失败不阻断另一个；每次同步追加 台账/32_镜像同步记录.csv 留痕。

熔断器（避免反复重试缺陷）：
- 认证失败（Authentication failed / 403 / 等）→ 对目标 remote 置「阻断」状态，
  后续运行**直接跳过不再重试**，也不写 32 台账（凭据留痕不入库）。
  仅当凭据更新（token 哈希变化）或显式 --force/--unblock 才解除。
- 网络/其他失败（连接重置/超时/DNS 等）→ **默认自动真实 IP 回退**（P-001：
  origin/github 先试上次成功 IP 缓存，失效则探测候选「可达+TLS 证书合法」IP 绑定推送，
  `--no-realip` 关闭）→ 仍失败才置「冷却」状态（默认 15 分钟），
  冷却期内跳过不重试（避免 flapping 时每次提交都重试并污染台账）。
- 无新提交（Everything up-to-date）→ 视为「已同步」，跳过且不写台账，
  避免每次提交后钩子自动双推时再留痕造成脏工作区。
- 状态存于 .secrets/mirror_push_state.json（gitignore，不入库）。
- 退出码：0=全部成功；1=存在本次尝试失败；2=全部被阻断/冷却跳过（未尝试）。
- 辅助命令：--force（无视阻断/冷却立即尝试）、--unblock <remote|all>（解除）、
  --status（查看当前状态）。

安全约定（铁律 #3 A 级）：
- 国内/境外 token 只经环境变量或 .secrets/ 提供，脚本从 GITEE_TOKEN/GITEE_USER 等读取，
  经 `git -c url.<auth>@.insteadOf=...` 注入，绝不打印、不写入仓库、不硬编码。
- 凭据获取跨平台走 `load_secret.load()`：环境变量 > .secrets/<name> 文件 > macOS Keychain；
  Windows 用 .secrets 文件或环境变量，macOS 额外支持系统钥匙串。
- 远程 URL 入台账前一律脱敏（掩去 user:token）。

用法（跨平台）：
  py -3.11 tools/mirror_push.py                # Windows（默认网络失败自动真实 IP 回退）
  python3 tools/mirror_push.py                 # macOS / Linux（同上）
py -3.11 tools/mirror_push.py origin mirror  # 指定 remote 列表
   py -3.11 tools/mirror_push.py --verify       # 仅校验各 remote 与本地 HEAD 是否一致
   py -3.11 tools/mirror_push.py --force        # 无视阻断/冷却，立即重试
   py -3.11 tools/mirror_push.py --no-realip    # 关闭 origin/github 网络失败时的真实 IP 自动回退（默认开启）
   py -3.11 tools/mirror_push.py --status       # 查看各 remote 阻断/冷却状态
   py -3.11 tools/mirror_push.py --unblock mirror  # 解除指定 remote 阻断/冷却
   py -3.11 tools/mirror_push.py --unblock      # 解除全部
  # 凭据三种提供方式（任选，脚本自动装载，无需手动 export）：
  #   a) 环境变量： $env:GITEE_TOKEN="xxx"; $env:GITEE_USER="gogojaja"   (Windows)
  #                export GITEE_TOKEN="xxx"; export GITEE_USER="gogojaja" (macOS)
  #   b) 文件：     .secrets/gitee_token 与 .secrets/gitee_user（gitignore，不入库）
  #   c) macOS：    security add-generic-password -s gitee_token -a <user> -w <token>
"""
import os
import sys
import re
import csv
import io
import json
import hashlib
import datetime
import subprocess

# GitHub 真实 IP 推送公共逻辑（P-001）：网络失败时 origin/github 走真实 IP 回退
try:
    import github_push as gp
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import github_push as gp

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
STATE_FILE = os.path.join(ROOT, ".secrets", "mirror_push_state.json")
BOM = b"\xef\xbb\xbf"
# 铁律 #8：32 台账入库前对真实 IP 脱敏，避免 B 级门禁拦截与敏感泄露。
_IP_RE = re.compile(r'(\d{1,3}\.){3}\d{1,3}')


def _mask_ip(s):
    return _IP_RE.sub('xxx.xxx.xxx.xxx', s) if isinstance(s, str) else s
DEFAULT_REMOTES = ["origin", "mirror"]
NETWORK_COOLDOWN = 15 * 60  # 秒：网络/其他失败后的冷却期

AUTH_FAIL_RE = re.compile(
    r"Authentication failed|Authentication succeeded but authorization failed"
    r"|access denied|forbidden|invalid credential|bad credentials|could not read (Username|Password)"
    r"|Repository not found", re.IGNORECASE)
NET_FAIL_RE = re.compile(
    r"Failed to connect|Could not connect|Connection was reset|Recv failure|timed? out"
    r"|Could not resolve host|Name or service not known|network is unreachable|Connection refused"
    r"|Operation timed out|Temporary failure in name resolution", re.IGNORECASE)

# remote -> (user_env, token_env)
TOKEN_ENV = {
    "mirror": ("GITEE_USER", "GITEE_TOKEN"),
    "gitee": ("GITEE_USER", "GITEE_TOKEN"),
    "gitcode": ("GITCODE_USER", "GITCODE_TOKEN"),
    "origin": ("GITHUB_USER", "GITHUB_TOKEN"),
    "github": ("GITHUB_USER", "GITHUB_TOKEN"),
}


def _run(cmd, extra_env=None, timeout=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        # encoding=utf-8 + errors=replace：避免 Windows 默认 GBK 解码 git UTF-8 输出时抛 UnicodeDecodeError
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        from types import SimpleNamespace
        return SimpleNamespace(returncode=124, stdout="", stderr="[timeout %ss]" % timeout)


def _branch():
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    b = r.stdout.strip()
    return b or "main"


def _head():
    return _run(["git", "rev-parse", "HEAD"]).stdout.strip()


def _mask(url):
    """脱敏：掩去 user:token。"""
    return re.sub(r"://[^/@]+@", "://***@", url) if url else ""


def _remote_exists(remote):
    r = _run(["git", "remote", "get-url", remote])
    return r.returncode == 0 and r.stdout.strip() != ""


def _resolve_credentials(remote):
    user_var, token_var = TOKEN_ENV.get(remote, (remote.upper() + "_USER", remote.upper() + "_TOKEN"))
    user = os.environ.get(user_var) or os.environ.get(user_var.lower())
    token = os.environ.get(token_var) or os.environ.get(token_var.lower())
    if token and not user:
        user = os.environ.get("GITEE_USER") or os.environ.get("GITHUB_USER")
    return user, token


def _push_one(remote, branch):
    """推送单个 remote；token 经 insteadOf 注入，不持久化。返回 (ok, msg, elapsed_sec)。"""
    user, token = _resolve_credentials(remote)

    extra_args = []
    if token:
        url = _run(["git", "remote", "get-url", remote]).stdout.strip()
        if "://" in url:
            proto, rest = url.split("://", 1)
            host = rest.split("/", 1)[0]
            auth = ("%s:" % user if user else "") + token + "@"
            instead = "%s://%s%s/" % (proto, auth, host)
            orig = "%s://%s/" % (proto, host)
            extra_args = ["-c", "url.%s.insteadOf=%s" % (instead, orig)]

    cmd = ["git", *extra_args,
           "-c", "http.connectTimeout=12",
           "-c", "http.lowSpeedLimit=1000",
           "-c", "http.lowSpeedTime=30",
           "push", remote, branch]
    start = datetime.datetime.now()
    res = _run(cmd, timeout=40)
    elapsed = (datetime.datetime.now() - start).total_seconds()
    ok = res.returncode == 0
    out = (res.stdout + res.stderr).strip()
    for s in (token, user):  # 铁律 #3 A 级：输出中抹除凭据，绝不回显/落盘
        if s:
            out = out.replace(s, "***")
    last = out.splitlines()[-1] if out else ""
    return ok, (last if last else ("成功" if ok else "失败")), elapsed


def _classify_failure(msg):
    """把 git push 失败信息归类为 auth / network / other，供熔断器决策。"""
    m = msg or ""
    if AUTH_FAIL_RE.search(m):
        return "auth"
    if NET_FAIL_RE.search(m):
        return "network"
    return "other"


IP_CACHE_FILE = os.path.join(ROOT, ".secrets", "gh_push_ip_cache.txt")


def _read_ip_cache():
    """读取上次真实 IP 回退成功的 github.com IP（加速后续回退，避免每次全量探测）。"""
    try:
        with io.open(IP_CACHE_FILE, "r", encoding="utf-8") as f:
            ip = f.read().strip()
        return ip if ip else None
    except Exception:
        return None


def _write_ip_cache(ip):
    try:
        os.makedirs(os.path.dirname(IP_CACHE_FILE), exist_ok=True)
        with io.open(IP_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(ip)
    except Exception:
        pass


def _real_ip_push(remote, branch, token, user, cached_ip):
    """真实 IP 回退推送 github 类 remote。先试缓存 IP（免探测），失败则探测候选。
    返回 (ok, msg, elapsed)；ok=False 时 msg 为最终失败信息。"""
    if cached_ip:
        ok, msg, el = gp._push_with_ip(cached_ip, branch, token, user, timeout=15)
        if ok:
            return True, "PUSH_OK %s (cached): %s" % (cached_ip, msg), el
        print("[回退] 缓存 IP %s 失效：%s" % (cached_ip, msg))
    print("[回退] %s 网络失败，探测 github.com 真实 IP ..." % remote)
    ip = gp.probe_best_github_ip()
    if not ip:
        return False, "无可用 github.com 真实 IP（候选全部不可达）", 0.0
    ok, msg, el = gp._push_with_ip(ip, branch, token, user, timeout=40)
    if ok:
        _write_ip_cache(ip)
        return True, "PUSH_OK %s: %s" % (ip, msg), el
    return False, "IP=%s: %s" % (ip, msg), el


def _token_hash(token):
    """凭据指纹：用于检测 token 是否更新，从而自动解除阻断。"""
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with io.open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    try:
        d = os.path.dirname(STATE_FILE)
        if not os.path.isdir(d):
            os.makedirs(d)
        with io.open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("  (状态文件写入失败: %s)" % e)


def _status(remotes):
    state = _load_state()
    shown = remotes if remotes else (list(state.keys()) if state else DEFAULT_REMOTES)
    for r in shown:
        st = state.get(r)
        if not st:
            print("[%s] 正常（无阻断/冷却）" % r)
        else:
            print("[%s] %s" % (r, json.dumps(st, ensure_ascii=False)))
    return 0


def _unblock(remotes):
    state = _load_state()
    if not remotes:
        state = {}
        print("已解除全部 remote 的阻断/冷却状态")
    else:
        for r in remotes:
            if r in state:
                del state[r]
                print("已解除 %s 的阻断/冷却状态" % r)
            else:
                print("%s 无阻断/冷却状态" % r)
    _save_state(state)
    return 0


def _next_seq():
    """幂等序号（P-005）：解析 SYNC-YYYYMMDD-NNN 取 max+1，避免双端并发追加冲突。"""
    if not os.path.exists(LEDGER):
        return 1
    maxn = 0
    with io.open(LEDGER, "r", encoding="utf-8-sig") as f:
        for line in f:
            m = re.search(r"SYNC-\d{8}-(\d+)", line)
            if m:
                maxn = max(maxn, int(m.group(1)))
    return maxn + 1


def _append_ledger(rows):
    header = ["同步编号", "同步时间", "源commit", "目标remote", "远程URL(脱敏)", "状态", "耗时秒", "说明"]
    new = not os.path.exists(LEDGER)
    with io.open(LEDGER, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        for row in rows:
            w.writerow([_mask_ip(c) for c in row])


def _commit_ledger_via_agent_loop():
    """写账后若启用 agent-loop（根目录 .agent-loop-enabled 且非递归上下文），
    交由 agent_loop.py --commit-only 统一提交 32/34 台账，消除手动推送后的工作区脏残留。
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


def _verify(remotes, branch):
    """启动即双端同步检查（P-002）：fetch 后对比本地与各远端领先/落后，存在分叉即阻断推送。"""
    head = _head()
    print("本地 HEAD: %s" % head[:12])
    all_ok = True
    for remote in remotes:
        if not _remote_exists(remote):
            print("  [%s] 跳过(未配置)" % remote)
            continue
        _run(["git", "fetch", remote, branch])
        r = _run(["git", "rev-parse", "%s/%s" % (remote, branch)])
        rh = r.stdout.strip()
        if not rh:
            print("  [%s] ⚠️ remote 无该分支，无法对比" % remote)
            all_ok = False
            continue
        if rh == head:
            print("  [%s] 与本地一致 (HEAD=%s)" % (remote, head[:12]))
            continue
        behind = _run(["git", "rev-list", "--count", "HEAD..%s/%s" % (remote, branch)]).stdout.strip()
        ahead = _run(["git", "rev-list", "--count", "%s/%s..HEAD" % (remote, branch)]).stdout.strip()
        if behind and behind != "0":
            print("  [%s] ⚠️ 远端领先 %s 提交（本地落后）——存在分叉，禁止直接推送！" % (remote, behind))
            print("      处理：git fetch %s && git merge %s/%s（或 rebase）后再推" % (remote, remote, branch))
            all_ok = False
        else:
            print("  [%s] 本地领先 %s 提交，可推送 (远端=%s)" % (remote, ahead, rh[:12]))
    return 0 if all_ok else 1


def _ensure_secrets():
    """跨平台自动装载凭据到环境变量（env > .secrets 文件 > macOS Keychain）。"""
    try:
        import load_secret as ls
    except Exception:
        return
    for n in ("gitee_token", "github_token"):
        try:
            u, t = ls.load(n)
        except Exception:
            continue
        if not t:
            continue
        key = n.upper()  # GITEE_TOKEN / GITHUB_TOKEN
        os.environ.setdefault(key, t)
        if u:
            os.environ.setdefault(key.replace("TOKEN", "USER"), u)


def main():
    _ensure_secrets()
    argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith("-")]
    verify = "--verify" in argv
    force = "--force" in argv
    status_only = "--status" in argv
    unblock = "--unblock" in argv
    github_realip = True
    if "--no-realip" in argv or "-r" in argv:
        github_realip = False
    elif "--github-realip" in argv:
        github_realip = True

    if status_only:
        return _status(args)
    if unblock:
        return _unblock(args)
    remotes = args if args else DEFAULT_REMOTES
    if verify:
        return _verify(remotes, _branch())

    branch = _branch()
    head = _head()
    now = datetime.datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    seq = _next_seq()
    rows = []
    state = _load_state()
    attempted = 0
    failed = 0
    skipped = 0

    for remote in remotes:
        if not _remote_exists(remote):
            sid = "SYNC-%s-%03d" % (now.strftime("%Y%m%d"), seq)
            seq += 1
            rows.append([sid, now_str, head[:12], remote, "",
                         "跳过(未配置)", "0.0", "remote 未配置，待用户在 Gitee 建仓后 git remote add mirror"])
            print("[跳过] %s：remote 未配置" % remote)
            continue

        st = state.get(remote, {})
        user, token = _resolve_credentials(remote)

        # ---- 熔断：认证失败阻断（凭据更新后自动解除）----
        if st.get("blocked") and not force:
            cur_hash = _token_hash(token)
            if token and st.get("token_hash") and cur_hash != st.get("token_hash"):
                print("[解除] %s：检测到凭据变更，自动解除阻断" % remote)
                st = {}
            else:
                print("[阻断] %s：%s（已停止重试；更新凭据后自动解除，或 --force 立即重试，或 --unblock 手动解除）"
                      % (remote, st.get("message", "凭据认证失败")))
                skipped += 1
                continue

        # ---- 熔断：网络/其他失败冷却期 ----
        if st.get("cooldown_until") and not force:
            try:
                cu = datetime.datetime.strptime(st["cooldown_until"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                cu = None
            if cu and now < cu:
                left = int((cu - now).total_seconds() // 60) + 1
                print("[冷却] %s：%s，约 %d 分钟后重试（--force 立即重试）"
                      % (remote, st.get("message", "网络不可达"), left))
                skipped += 1
                continue
            st = {}

        # ---- 实际推送 ----
        attempted += 1
        url = _run(["git", "remote", "get-url", remote]).stdout.strip()
        ok, msg, elapsed = _push_one(remote, branch)
        sid = "SYNC-%s-%03d" % (now.strftime("%Y%m%d"), seq)
        seq += 1

        if ok:
            state.pop(remote, None)
            if "up-to-date" in msg:
                # 无新提交可推：视为「已同步」，不写台账，避免每次提交后钩子再留痕造成脏工作区
                print("[跳过] %s：已同步（无新提交，不写台账）" % remote)
                continue
            rows.append([sid, now_str, head[:12], remote, _mask(url),
                         "成功", "%.1f" % elapsed, msg])
            print("[成功] %s：%s (%.1fs)" % (remote, msg, elapsed))
        else:
            cls = _classify_failure(msg)
            if cls == "auth":
                # 凭据问题：阻断重试，不入 32 台账（铁律：凭据失败留痕不入库，避免污染工作区）
                failed += 1
                state[remote] = {"blocked": True, "reason": "auth",
                                 "token_hash": _token_hash(token),
                                 "message": "凭据认证失败（需提供新 token）", "updated_at": now_str}
                print("[阻断] %s：凭据认证失败，已停止重试。请更新凭据（.secrets/<remote>_token 或环境变量）后自动解除，"
                      "或 --force 立即重试，或 --unblock 手动解除。" % remote)
            else:
                # ---- 网络类失败：默认自动真实 IP 回退（P-001，--no-realip 可关）----
                ok2 = False
                if github_realip and remote in ("origin", "github"):
                    print("[回退] %s 网络失败，尝试真实 IP 推送 ..." % remote)
                    ok2, msg2, elapsed2 = _real_ip_push(
                        remote=remote, branch=branch, token=token, user=user,
                        cached_ip=_read_ip_cache())
                    if ok2:
                        state.pop(remote, None)
                        rows.append([sid, now_str, head[:12], remote, _mask(url),
                                     "成功", "%.1f" % elapsed2, msg2])
                        print("[成功] %s：真实IP回退 %s (%.1fs)" % (remote, msg2, elapsed2))
                        continue
                if not ok2:
                    state[remote] = {"blocked": False, "reason": cls, "message": msg,
                                     "cooldown_until": (now + datetime.timedelta(seconds=NETWORK_COOLDOWN)).strftime("%Y-%m-%d %H:%M:%S"),
                                     "updated_at": now_str}
                    failed += 1
                    rows.append([sid, now_str, head[:12], remote, _mask(url),
                                 "失败", "%.1f" % elapsed, msg])
                    print("[失败] %s：%s (%.1fs)" % (remote, msg, elapsed))
                    print("  详情：%s" % msg)

    _save_state(state)
    if rows:
        _append_ledger(rows)
        print("\n台账已更新：%s" % LEDGER)
        _commit_ledger_via_agent_loop()
    print("本地 HEAD=%s  尝试=%d  失败=%d  跳过=%d" % (head[:12], attempted, failed, skipped))
    if attempted == 0:
        sys.exit(2)  # 全部被阻断/冷却跳过（未尝试）——agent_loop 记为「跳过(阻断)」
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
