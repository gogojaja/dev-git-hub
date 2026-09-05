#!/bin/bash
# install.sh — 安装 dev-git-hub post-commit 钩子
# 用法：在目标仓库根目录运行 bash /path/to/dev-git-hub/hooks/install.sh
# 效果：将 git core.hooksPath 指向本目录，启用自动三推

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== dev-git-hub hooks 安装 ==="
echo "钩子目录：$SCRIPT_DIR"
echo ""

# 检查 post-commit 是否存在
if [ ! -f "$SCRIPT_DIR/post-commit" ]; then
    echo "[错误] 未找到 $SCRIPT_DIR/post-commit"
    exit 1
fi

# 设置 core.hooksPath（全局生效，影响所有仓库）
git config --global core.hooksPath "$SCRIPT_DIR"
echo "[完成] 已设置 git config --global core.hooksPath = $SCRIPT_DIR"
echo ""

# 验证
CONFIGURED=$(git config --global core.hooksPath)
# Normalize paths for comparison (handle /d/... vs D:/... on Windows/Git Bash)
CONFIGURED_NORM=$(cd "$CONFIGURED" 2>/dev/null && pwd -W 2>/dev/null || echo "$CONFIGURED")
SCRIPT_NORM=$(cd "$SCRIPT_DIR" 2>/dev/null && pwd -W 2>/dev/null || echo "$SCRIPT_DIR")
if [ "$CONFIGURED_NORM" = "$SCRIPT_NORM" ] || [ "$CONFIGURED" = "$SCRIPT_DIR" ]; then
    echo "[验证通过] core.hooksPath 已生效"
    echo ""
    echo "现在所有 git 仓库的 post-commit 都将触发自动三推。"
    echo "跳过方式：commit message 中加入 [skip-push]"
    echo "日志位置：\$HOME/.git/mirror_push.log"
else
    echo "[验证失败] core.hooksPath 设置异常：$CONFIGURED"
    exit 1
fi
