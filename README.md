# dev-git-hub — 局域网 Git 基建（独立项目）

> **定位**：独立 git 基建项目，承载「Mac 局域网 bare 中枢 + Windows 全量副本 + WAN 灾备」三层拓扑。
> **职责边界**：只做 git 基建（服务器/副本/同步策略），**不承载任何业务/技能库代码**。
> **解耦原则**：所有本机环境配置（IP/路径/密钥）进 `config.example.yaml`，换机器只改配置不改结构。
> **授权**：AUTH-014（2026-08-30 用户采纳方案 A，长期有效）
> **关联**：DevProjectTeamSkill（技能库，本项目仅在本技能库 AGENTS.md / TwinForge 方案中登记引用，不内嵌）

---

## 一、拓扑

| 层 | 角色 | 说明 |
|----|------|------|
| **LAN 中枢** | Mac mini bare 仓库（`~/git/hub/dev-project-team-skill.git`） | 日常 push 主目标（LAN 秒级、无 WAN 抖动） |
| **Windows 副本** | Windows 全量克隆（`git clone` 天然含全部历史/分支） | 全量备份 + 断网可用 + 快速本地访问 |
| **WAN 灾备** | GitHub(origin) + Gitee(mirror) 保持 | 跨地/发布时推，LAN 单点兜底 |

## 二、文件结构

```
dev-git-hub/
  ├── README.md              本文件
  ├── config.example.yaml    本机环境配置层（IP/路径/密钥，与硬件解耦）
  ├── install_mac.sh         Mac 建 bare 中枢 + SSH over LAN（本机步骤）
  ├── install_windows.ps1    Windows 全量克隆副本（Dell/OptiPlex）
  └── sync_policy.md         同步策略（日常 LAN push + 定期 WAN 灾备 + 反信号）
```

## 三、核心技术选型（最小依赖）

- **git over SSH + bare repository**：已装 `/usr/sbin/sshd`，零新增依赖（15MB 单仓无需 Gitea/GitLab）
- **git clone 即全量备份**：Windows 克隆副本自动含全部历史/分支

## 四、日常流程

```bash
# 日常提交（LAN 秒级，替代频繁 WAN 推送重试）
git push hub main

# 定期灾备（按需/周末）
(mirror_push WAN 双推 GitHub + Gitee)

# 断网/跨机可用
Windows 副本 git pull hub（或直接本地工作）
```

## 五、反信号（防过度工程）

- 2 阶段内 LAN push 未成常态 → 撤回，仅保留 WAN 双推
- Mac mini 长期关机 → 不可行，Windows 副本 + WAN 兜底

---

**最后更新**：2026-08-30（初始创建，方案/评审产物见 DevProjectTeamSkill/docs/局域网git服务器方案.md）