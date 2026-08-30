# =============================================================================
# install_windows.ps1 — Windows 端全量克隆副本（dev-git-hub M4，Dell/OptiPlex）
# 前置：Windows 已装 Git for Windows（TwinForge § 软件清单已列「已有」）
# 用法：.\install_windows.ps1   （按 config.yaml 填写 URL/目录）
# 安全：仅 git clone 全部历史（无凭据写入脚本）；敏感信息经凭据管理器
# =============================================================================
param(
  [string]$HubUrl = "ssh://<hub-user>@192.168.x.x/~/git/hub/dev-project-team-skill.git",
  [string]$Workspace = "C:\git-repos"
)

Write-Host "== dev-git-hub Windows 端全量克隆 =="
Write-Host "Hub: $HubUrl | Workspace: $Workspace"

# 确保工作目录存在
if (-not (Test-Path $Workspace)) { New-Item -ItemType Directory -Path $Workspace | Out-Null }

# 克隆（若已存在则 pull 更新）
$target = Join-Path $Workspace "DevProjectTeamSkill"
if (Test-Path $target) {
  Write-Host "[info] 副本已存在，git pull 更新..."
  Push-Location $target
  git pull hub main 2>$null
  git pull origin main 2>$null   # WAN 兜底
  Pop-Location
} else {
  Write-Host "[step] 全量克隆（含全部历史/分支，即自动备份）..."
  Push-Location $Workspace
  git clone $HubUrl DevProjectTeamSkill
  Pop-Location
  # 保留 WAN 远端（灾备）
  Push-Location $target
  git remote add origin https://github.com/gogojaja/DevProjectTeamSkill.git
  git remote add mirror https://gitee.com/gogojaja/DevProjectTeamSkill.git
  Pop-Location
}

Write-Host "[ok] Windows 副本就绪: $target"
Write-Host "留痕：本副本属项目外机器（TwinForge Dell），已按 DevProjectTeamSkill 铁律#7a 授权（AUTH-014）。"
Write-Host "断网可用：本副本含全部历史/分支，可在 Windows 离线工作后 git push hub/pull 同步。"