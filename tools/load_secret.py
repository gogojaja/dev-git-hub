#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_secret.py — 跨平台凭据读取（铁律 #3 A 级：真实值只经 env / .secrets / 系统钥匙串，绝不入库）

优先级（跨平台一致）：
  1. 环境变量 <NAME>_TOKEN / <NAME>_USER
  2. 仓库内 .secrets/<name>（gitignore，不入库）
  3. macOS Keychain：security find-generic-password -s <name> -w
     （Windows Credential Manager 取密需 COM/第三方，暂不取，回退到第 2 项文件方式）

用法：
  py -3.11 tools/load_secret.py gitee_token          # Windows
  python3 tools/load_secret.py gitee_token           # macOS
可作为模块被 mirror_push.py 调用：user, token = load_secret.load("gitee_token")
"""
import os
import sys
import io
import platform
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_DIR = os.path.join(ROOT, ".secrets")


def load(name, user_name=None):
    """返回 (user, token)。取不到 token 时返回 (user, "")。

    name 约定为小写基名，如 "gitee_token"：
      - 环境变量：GITEE_TOKEN / GITEE_USER
      - 文件：.secrets/gitee_token / .secrets/gitee_user
      - macOS Keychain service：-s gitee_token
    """
    token_var = name.upper()                       # gitee_token -> GITEE_TOKEN
    user_var = token_var.replace("TOKEN", "USER")  # GITEE_USER
    token = os.environ.get(token_var)
    user = os.environ.get(user_var)
    if token:
        return user, token

    # 2) .secrets/<name> 文件（gitignore）
    tok_path = os.path.join(SECRET_DIR, name)
    usr_path = os.path.join(SECRET_DIR, name.replace("token", "user"))
    if os.path.exists(tok_path):
        try:
            token = io.open(tok_path, "r", encoding="utf-8").read().strip()
        except Exception:
            token = ""
        if os.path.exists(usr_path):
            try:
                user = io.open(usr_path, "r", encoding="utf-8").read().strip()
            except Exception:
                pass
        if token:
            return user, token

    # 3) macOS Keychain
    if platform.system() == "Darwin":
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-s", name, "-w"],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                return user, r.stdout.strip()
        except Exception:
            pass

    return user, token or ""


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "gitee_token"
    user, token = load(name)
    if token:
        # 仅确认“已取到”，绝不回显明文
        print("OK: %s 已取到 (长度 %d)" % (name, len(token)))
        sys.exit(0)
    sys.stderr.write(
        "MISS: %s 未找到。请设环境变量 %s，或写 %s，或(macOS)存入 Keychain：\n"
        "  security add-generic-password -s %s -a <user> -w <token>\n"
        % (name, name.upper(), os.path.join(SECRET_DIR, name), name)
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
