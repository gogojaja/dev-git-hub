#!/usr/bin/env bash
# =============================================================================
# install_mac.sh — Mac 端安装：建 bare 中枢 + SSH over LAN（dev-git-hub M1~M2）
# 安全：SSH 密钥认证（禁密码登录）；操作留痕（13 审计台账）；本机操作
# 用法：bash install_mac.sh  或  bash install_mac.sh <仓库名>
# =============================================================================
set -euo pipefail

REPO="${1:-dev-project-team-skill.git}"
HUB_ROOT="${HUB_ROOT:-$HOME/git/hub}"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo UNKNOWN)"

echo "== dev-git-hub Mac 端安装 =="
echo "LAN IP: $LAN_IP | 仓库: $REPO | 中枢根: $HUB_ROOT"

# ---- M1 建 bare 中枢 ----
mkdir -p "$HUB_ROOT"
if [ -d "$HUB_ROOT/$REPO" ]; then
  echo "[info] bare 中枢已存在: $HUB_ROOT/$REPO"
else
  git init --bare "$HUB_ROOT/$REPO"
  echo "[ok] 已创建 bare 中枢: $HUB_ROOT/$REPO"
fi

# ---- M2 SSH over LAN（密钥认证 + 禁密码提示，不自动改系统安全设置） ----
KEYFILE="$HOME/.ssh/id_ed25519.pub"
if [ -f "$KEYFILE" ]; then
  echo "[ok] 已有 ED25519 公钥: $KEYFILE"
else
  echo "[warn] 未找到 $HOME/.ssh/id_ed25519.pub"
  echo "[warn] 请生成: ssh-keygen -t ed25519，或复制已有公钥到 authorized_keys"
fi

echo ""
echo "SSH 就绪检查（手工/管理员步骤，避免脚本越权改系统设置）："
echo "1. 确认 sshd 运行: sudo systemsetup -setremotelogin on （如未开）"
echo "2. 公钥授权: 将 ~/.ssh/id_ed25519.pub 追加到 ~/.ssh/authorized_keys"
echo "3. （建议安全）编辑 /etc/ssh/sshd_config 设 PasswordAuthentication no"
echo "4. 验证: ssh -o BatchMode=yes $USER@127.0.0.1 echo OK"
echo ""
echo "[留痕] 本操作登记 13 审计: dev-git-hub Mac 安装（M1 bare + M2 SSH 就绪）"
echo "日常推送: git remote add hub ssh://$USER@$LAN_IP/$HUB_ROOT/$REPO && git push hub --all"
