#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描本地无远程的 git 仓库，在 Mac mini bare 中枢上自动新建 bare 仓库并推送。

归属：dev-git-hub（git 基建单一信源，AUTH-014）。2026-09-05 自 DevProjectTeamSkill 迁入（整改 R-1），
原仓库侧保留同名薄代理转发至本脚本，命令/参数完全兼容。

适用场景：
  - 本地有不能推互联网的 git 仓库，需推到 Mac 局域网 bare 中枢
  - 任意 Windows 机器（装了 Tailscale + git + ssh）均可使用

使用方式：
  python tools/init_mac_bare_repos.py --scan-only                         # 仅扫描
  python tools/init_mac_bare_repos.py --dry-run                           # 预览
  python tools/init_mac_bare_repos.py                                     # 推送所有无远程仓库
  python tools/init_mac_bare_repos.py --repos A B C                       # 推送指定仓库
  python tools/init_mac_bare_repos.py --force                             # 追加 hub remote 到所有仓库
  python tools/init_mac_bare_repos.py --list                              # 列出 Mac 上已有的 bare 仓库
  python tools/init_mac_bare_repos.py --clone --repos A                   # 从 Mac 克隆到本地

依赖：标准库 + git + ssh（均已预装）

跨机器使用：
  将本脚本复制到任意 Windows 机器，修改下方 LOCAL_SCAN_DIRS 或用 --scan-dir 参数指定目录。

注意：
  - 本脚本通过 SSH 写入 Mac 文件系统，执行前须获得用户明确授权
  - MAC_USER / MAC_HOST / MAC_BARE_BASE / DEFAULT_SCAN_DIRS 为脚本内常量（可用
    --mac-host / --scan-dir 覆盖），后续建议纳入 config.yaml 解耦层（整改 R-1 后续项）
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path

# ---- 配置（可通过命令行参数覆盖） ----
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", str(Path(__file__).resolve().parent.parent)))
DEFAULT_SCAN_DIRS = [
    Path(r"D:\Myprojects"),   # Dell 主工作目录
]
MAC_USER = "gogo"
MAC_HOST = "100.101.130.81"   # Tailscale IP（可通过 --mac-host 覆盖）
MAC_BARE_BASE = "~/git/hub"   # Mac 上 bare 仓库根目录
REMOTE_NAME = "hub"            # 本地 git remote 名称


def run(cmd, cwd=None, capture=True, timeout=30):
    """执行命令，返回 (returncode, stdout, stderr)。"""
    r = subprocess.run(
        cmd, cwd=cwd, capture_output=capture, text=True,
        timeout=timeout, encoding="utf-8", errors="replace"
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def ssh_cmd(command):
    """构造 SSH 命令列表。"""
    return [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        f"{MAC_USER}@{MAC_HOST}",
        command
    ]


def is_git_repo(path):
    """判断目录是否为 git 仓库。"""
    git_dir = path / ".git"
    return git_dir.exists() and git_dir.is_dir()


def get_remotes(path):
    """获取仓库的 remote 列表。"""
    rc, out, _ = run(["git", "remote"], cwd=path)
    if rc != 0:
        return []
    return [r.strip() for r in out.splitlines() if r.strip()]


def get_repo_name(path):
    """获取仓库名（目录名）。"""
    return path.name


def get_branch(path):
    """获取当前分支名。"""
    rc, out, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return out if rc == 0 else "main"


def check_ssh():
    """测试 Mac SSH 连通性。"""
    rc, out, err = run(ssh_cmd("echo SSH_OK"), timeout=8)
    return rc == 0 and "SSH_OK" in out, err


def mac_list_bare():
    """列出 Mac 上 bare 仓库目录下所有 .git 仓库。"""
    cmd = ssh_cmd(
        f"if [ -d {MAC_BARE_BASE} ]; then "
        f"  ls -1d {MAC_BARE_BASE}/*.git 2>/dev/null | xargs -I{{}} basename {{}} .git"
        f"else echo 'NO_DIR'; fi"
    )
    rc, out, err = run(cmd, timeout=8)
    if "NO_DIR" in out:
        return []
    return [r.strip() for r in out.splitlines() if r.strip()]


def mac_clone_repo(repo_name, local_dir):
    """从 Mac bare 仓库克隆到本地。"""
    remote_url = f"{MAC_USER}@{MAC_HOST}:{MAC_BARE_BASE}/{repo_name}.git"
    rc, out, err = run(
        ["git", "clone", remote_url, str(local_dir)],
        timeout=120
    )
    return rc == 0, out + "\n" + err


def mac_bare_exists(repo_name):
    """检查 Mac 上 bare 仓库是否已存在。"""
    cmd = ssh_cmd(f"test -d {MAC_BARE_BASE}/{repo_name}.git && echo EXISTS || echo NOT_FOUND")
    rc, out, _ = run(cmd, timeout=8)
    return "EXISTS" in out


def mac_create_bare(repo_name):
    """在 Mac 上创建 bare 仓库目录并初始化。"""
    cmd = ssh_cmd(
        f"mkdir -p {MAC_BARE_BASE} && "
        f"cd {MAC_BARE_BASE} && "
        f"git init --bare {repo_name}.git 2>&1 && "
        f"echo CREATE_OK"
    )
    rc, out, err = run(cmd, timeout=10)
    return rc == 0 and "CREATE_OK" in out, out


def add_remote_and_push(path, repo_name):
    """添加 hub remote 并推送全部分支和标签。"""
    remote_url = f"{MAC_USER}@{MAC_HOST}:{MAC_BARE_BASE}/{repo_name}.git"

    # 检查 hub remote 是否已存在
    remotes = get_remotes(path)
    if REMOTE_NAME in remotes:
        print(f"    ⚠ remote '{REMOTE_NAME}' 已存在，跳过添加")
    else:
        rc, _, err = run(["git", "remote", "add", REMOTE_NAME, remote_url], cwd=path)
        if rc != 0:
            print(f"    ✗ 添加 remote 失败: {err}")
            return False

    # 推送全部分支 + 标签
    rc1, out1, err1 = run(["git", "push", REMOTE_NAME, "--all"], cwd=path, timeout=60)
    rc2, out2, err2 = run(["git", "push", REMOTE_NAME, "--tags"], cwd=path, timeout=30)

    ok = rc1 == 0
    if rc1 != 0:
        print(f"    ✗ push --all 失败: {err1}")
    else:
        print(f"    ✓ push --all 成功")
    if rc2 != 0 and "error" not in err2.lower():
        pass  # 没有标签也算正常
    else:
        print(f"    ✓ push --tags 成功")

    return ok


def scan_repos(scan_dirs):
    """扫描本地所有 git 仓库及其远程状态。"""
    repos = []
    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for item in scan_dir.iterdir():
            if item.is_dir() and is_git_repo(item):
                remotes = get_remotes(item)
                branch = get_branch(item)
                repos.append({
                    "path": item,
                    "name": get_repo_name(item),
                    "remotes": remotes,
                    "branch": branch,
                    "has_remote": len(remotes) > 0,
                })
    return repos


def main():
    global MAC_HOST

    parser = argparse.ArgumentParser(
        description="扫描本地无远程的 git 仓库，推送至 Mac bare 中枢",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s --scan-only                         # 仅扫描本地仓库状态
  %(prog)s --dry-run                           # 预览（不执行）
  %(prog)s                                     # 推送所有无远程仓库到 Mac
  %(prog)s --repos A B C                       # 推送指定仓库
  %(prog)s --force                             # 追加 hub remote 到所有仓库
  %(prog)s --list                              # 列出 Mac 上已有的 bare 仓库
  %(prog)s --clone --repos A                   # 从 Mac 克隆到本地
  %(prog)s --scan-dir E:\my-other-projects     # 指定扫描目录
  %(prog)s --mac-host 192.168.3.86             # 指定 Mac IP
"""
    )
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不执行实际操作")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描显示仓库状态")
    parser.add_argument("--force", action="store_true", help="对已有远程的仓库也执行推送（追加 hub remote）")
    parser.add_argument("--repos", nargs="*", help="指定要推送的仓库名（空格分隔）")
    parser.add_argument("--list", action="store_true", help="列出 Mac 上已有的 bare 仓库")
    parser.add_argument("--clone", action="store_true", help="从 Mac 克隆仓库到本地（配合 --repos 或不指定则全部）")
    parser.add_argument("--scan-dir", nargs="*", type=Path, help="指定扫描目录（覆盖默认 D:\\Myprojects）")
    parser.add_argument("--mac-host", help=f"Mac Tailscale IP（默认 {MAC_HOST}）")
    parser.add_argument("--local-dir", type=Path, help="克隆目标目录（--clone 时使用，默认当前目录）")
    args = parser.parse_args()

    if args.mac_host:
        MAC_HOST = args.mac_host

    print("=" * 60)
    print("  Mac bare 中枢推送工具")
    print(f"  目标: {MAC_USER}@{MAC_HOST}:{MAC_BARE_BASE}/")
    print("=" * 60)

    # ---- 0. 测试 SSH ----
    print("\n[0] 测试 Mac SSH 连通性...")
    ssh_ok, err = check_ssh()
    if not ssh_ok:
        print(f"  ✗ SSH 不通: {err}")
        print("\n  请先在 Mac 上开启 SSH：")
        print("    系统设置 → 通用 → 共享 → 远程登录 → 打开")
        print("  开启后重新运行本脚本。")
        return 1
    print(f"  ✓ SSH 连通 ({MAC_HOST})")

    # ---- --list: 列出 Mac 上已有 bare 仓库 ----
    if args.list:
        print("\n[LIST] Mac 上已有的 bare 仓库：")
        bare_repos = mac_list_bare()
        if not bare_repos:
            print("  (无)")
        else:
            for name in sorted(bare_repos):
                print(f"    • {name}")
            print(f"  共 {len(bare_repos)} 个 bare 仓库")
        print(f"\n  克隆：git clone {MAC_USER}@{MAC_HOST}:{MAC_BARE_BASE}/<仓库名>.git")
        return 0

    # ---- --clone: 从 Mac 克隆 ----
    if args.clone:
        print("\n[CLONE] 从 Mac 克隆 bare 仓库...")
        bare_repos = mac_list_bare()
        if not bare_repos:
            print("  Mac 上没有任何 bare 仓库")
            return 1

        target_repos = args.repos if args.repos else bare_repos
        clone_dir = args.local_dir or Path.cwd()
        clone_dir.mkdir(parents=True, exist_ok=True)

        ok_count = 0
        for name in target_repos:
            if name not in bare_repos:
                print(f"    ✗ {name}: Mac 上不存在")
                continue
            target = clone_dir / name
            if target.exists():
                print(f"    ⚠ {name}: 目标目录已存在 ({target})，跳过")
                continue
            print(f"    克隆 {name} → {target} ...")
            ok, out = mac_clone_repo(name, target)
            if ok:
                print(f"    ✓ {name} 克隆成功")
                ok_count += 1
            else:
                print(f"    ✗ {name} 克隆失败: {out}")
        print(f"\n  完成：{ok_count}/{len(target_repos)} 个仓库克隆成功")
        return 0 if ok_count == len(target_repos) else 1

    # ---- 1. 扫描本地仓库 ----
    scan_dirs = args.scan_dir if args.scan_dir else DEFAULT_SCAN_DIRS
    print(f"\n[1/4] 扫描本地 git 仓库（目录: {', '.join(str(d) for d in scan_dirs)}）...")
    repos = scan_repos(scan_dirs)
    no_remote = [r for r in repos if not r["has_remote"] or args.force]
    if args.repos:
        no_remote = [r for r in no_remote if r["name"] in args.repos]

    if not repos:
        print("  未发现任何 git 仓库")
        return 1

    print(f"\n  发现 {len(repos)} 个 git 仓库：\n")
    print(f"  {'仓库名':<35} {'分支':<12} {'远程仓库'}")
    print(f"  {'-'*35} {'-'*12} {'-'*40}")
    for r in repos:
        flag = " → 将推送" if r in no_remote else ""
        remote_str = ", ".join(r["remotes"]) if r["remotes"] else "(无)"
        print(f"  {r['name']:<35} {r['branch']:<12} {remote_str}{flag}")

    if args.scan_only:
        return 0

    if not no_remote:
        print("\n  ✓ 所有仓库都已有远程，无需推送（用 --force 可追加 hub remote）")
        return 0

    print(f"\n  待推送: {len(no_remote)} 个仓库")
    for r in no_remote:
        print(f"    • {r['name']}")

    # ---- 2. 创建 bare 仓库 + 推送 ----
    print("\n[2/4] 创建 bare 仓库并推送...")
    success = []
    failed = []

    for r in no_remote:
        name = r["name"]
        path = r["path"]
        print(f"\n  [{name}]")

        if args.dry_run:
            exists = mac_bare_exists(name)
            print(f"    (dry) Mac bare: {'已存在' if exists else '需新建'}")
            print(f"    (dry) git push {REMOTE_NAME} --all")
            success.append(name)
            continue

        # 检查 Mac 上是否已存在
        exists = mac_bare_exists(name)
        if exists:
            print(f"    Mac bare 仓库已存在: {MAC_BARE_BASE}/{name}.git")
        else:
            print(f"    创建 Mac bare 仓库: {MAC_BARE_BASE}/{name}.git ...")
            ok, out = mac_create_bare(name)
            if not ok:
                print(f"    ✗ 创建失败: {out}")
                failed.append(name)
                continue
            print(f"    ✓ 创建成功")

        # 推送
        print(f"    推送 {r['branch']} 分支 + 标签...")
        ok = add_remote_and_push(path, name)
        if ok:
            success.append(name)
        else:
            failed.append(name)

    # ---- 3. 汇总 ----
    print("\n" + "=" * 60)
    print(f"[3/3] 结果汇总")
    print(f"  成功: {len(success)} 个")
    for s in success:
        print(f"    ✓ {s}")
    if failed:
        print(f"  失败: {len(failed)} 个")
        for f in failed:
            print(f"    ✗ {f}")
    print("=" * 60)

    # ---- 后续操作提示 ----
    if success and not args.dry_run:
        print("\n后续操作：")
        print("  在 Mac 上可直接访问 bare 仓库：")
        print(f"    cd {MAC_BARE_BASE}/<仓库名>.git")
        print("  在其他机器克隆：")
        print(f"    git clone {MAC_USER}@{MAC_HOST}:{MAC_BARE_BASE}/<仓库名>.git")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
