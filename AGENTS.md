# dev-git-hub — AI Agent 指令

> 项目群归属：PG-LOCAL-001（Douglas 项目群），PMO = DevProjectTeamSkill (role-program-mgmt)
> 审核日期：2026-09-05（项目群边界审核 B-02）

## 职责边界（铁律）

### 定位

局域网 git 基建（Mac bare 中枢 + Windows 全量副本 + WAN 灾备）。

### 职责

- 承载所有 git 基建实现：mirror_push（三推：origin GitHub + mirror Gitee + hub LAN bare）、github_push（真实 IP 推送）、github_ip_refresh、init_mac_bare_repos（Mac bare 中枢初始化）
- 承载 git 基建标准文档（references/github_access.md 为单一信源）
- 承载凭据装载工具（load_secret.py，姊妹文件与 DevProjectTeamSkill 同步）
- 提供 config.example.yaml 解耦层（IP/路径/密钥与硬件解耦）

### 禁做

- 禁止承载任何业务/技能库代码
- 禁止保留非 git 基建领域的工具实现

### 对外接口

- 对外提供 tools/ 下所有 git 操作脚本（供 DevProjectTeamSkill 薄代理转发）
- 接受 PROJECT_ROOT 环境变量指定目标仓库
- DEV_GIT_HUB_ROOT / .hub_root 用于被代理方定位本项目

### 依赖

- SSH 连通性（Mac mini sshd）
- GitHub/Gitee 凭据（.secrets/ 或环境变量）

### 项目群归属

- PGO（项目群整体视图与管控）：DevProjectTeamSkill (role-program-mgmt)
- 本项目类型：工具库
- 本项目由 DevProjectTeamSkill 角色包按需调用，不独立承载项目群管理功能
