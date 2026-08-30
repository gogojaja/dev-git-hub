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
dev-git-hub/                    git 基建单一信源（本项目为唯一权威）
  ├── README.md                 本文件
  ├── 交接文档.md               跨会话断点 / 工作状态 / 接口契约（DevProjectTeamSkill 与本项目协同锚点）
  ├── config.example.yaml       本机环境配置层（IP/路径/密钥，与硬件解耦；真实 config.yaml 不入库）
  ├── install_mac.sh            Mac 建 bare 中枢 + SSH over LAN（本机步骤）
  ├── install_windows.ps1       Windows 全量克隆副本（Dell/OptiPlex）
  ├── sync_policy.md            同步策略（日常 LAN push + 定期 WAN 灾备 + 反信号）
  ├── tools/                    git 复杂远端操作工具（单一信源）
  │   ├── mirror_push.py        双推（支持 PROJECT_ROOT 环境变量 → 以目标仓库为工作根）
  │   ├── github_push.py        GitHub 真实 IP 推送（同 PROJECT_ROOT 支持）
  │   ├── github_ip_refresh.py / check_github_connectivity.py / restore_github_push.sh / _gh_ip_probe.py
  │   └── load_secret.py        凭据跨平台装载（环境变量 > .secrets > 钥匙串）
  ├── references/
  │   └── github_access.md      GitHub 访问异常处理标准
  └── docs/                     git 基建方案 / 证据卡 / 评审报告（单源，从 DevProjectTeamSkill 交接）
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

### 调用示例

#### 使用 `mirror_push.py` 双推 GitHub + Gitee
```bash
python /path/to/dev-git-hub/tools/mirror_push.py
```

#### 使用 `github_push.py` 推送至 GitHub
```bash
python /path/to/dev-git-hub/tools/github_push.py
```

## 五、反信号（防过度工程）

- 2 阶段内 LAN push 未成常态 → 撤回，仅保留 WAN 双推
- Mac mini 长期关机 → 不可行，Windows 副本 + WAN 兜底

## 六、维护接口契约（跨项目协同，单一信源）

**本项目 = git 基建单一信源**（DevProjectTeamSkill 不保留实现，仅引用+代理调用）；**接口信息共享**：

| 接口 | 说明 |
|------|------|
| **环境变量 `PROJECT_ROOT` / `DPB_ROOT`** | 本库脚本以此为目标仓库工作根（读其远端/台账）；DevProjectTeamSkill 代理转发时注入其仓库根 |
| **工具调用** | DevProjectTeamSkill `tools/` 下同名薄封装代理 → 本库 `tools/` 真实实现（参数/命令兼容） |
| **方案/标准** | git 基建方案/证据卡/评审报告/github_access 标准**以本库 `docs/`+`references/` 为单一信源** |
| **维护动作** | 后续对本项目维护**经建议方案提供给本项目**，具体执行由本项目独立判断；改动只落本项目仓库 |
| **协作锚点** | `交接文档.md`（工作断点/阻塞/下一步）跨会话持续刷新 |
| **调用示例** | 其他项目可通过环境变量指定目标仓库：`PROJECT_ROOT=/path/to/other-repo python /path/to/dev-git-hub/tools/mirror_push.py` |

> DevProjectTeamSkill 定位为「项目孵化器」：对本项目只产出方案/建议，不代本项目落地；本项目独立判断执行，保持完整性与独立性。

### 其他项目调用示例

#### 1. 基本调用（对当前项目）
```bash
# 双推 GitHub + Gitee
python /path/to/dev-git-hub/tools/mirror_push.py

# 仅推 GitHub（真实 IP 机制）
python /path/to/dev-git-hub/tools/github_push.py

# 强制推送（覆盖分叉）
python /path/to/dev-git-hub/tools/mirror_push.py --git-force
```

#### 2. 跨项目调用（指定目标仓库）
```bash
# 对其他项目执行双推
export PROJECT_ROOT=/path/to/other-project
python /path/to/dev-git-hub/tools/mirror_push.py

# 对其他项目仅推 GitHub
export PROJECT_ROOT=/path/to/other-project
python /path/to/dev-git-hub/tools/github_push.py --force
```

#### 3. DevProjectTeamSkill 薄封装代理调用
```bash
# DevProjectTeamSkill 通过代理转发调用
# 代理脚本会自动注入 PROJECT_ROOT 环境变量
python /path/to/DevProjectTeamSkill/tools/mirror_push.py --target-repo /path/to/other-project
```

#### 4. 参数说明
- `--force`: 跳过熔断/冷却状态立即重试
- `--git-force`: 强制推送（覆盖分叉远端）
- `--verify`: 验证本地与远端一致性
- `--status`: 查看当前阻断/冷却状态
- `--unblock`: 解除阻断/冷却状态

---

**注意**：调用前请确保目标仓库已配置：
1. 有效的 `.secrets/github_token` 和 `.secrets/gitee_token`
2. 正确的 remote 配置（origin/mirror）
3. 凭据权限足够（repo/projects 权限）

---

**最后更新**：2026-08-30（完整交接建立：工具/标准/docs 单源迁入 + 交接文档.md + 维护接口契约 §六；初始创建见 git 历史）。本库 `docs/` 下 git 基建方案/证据卡/评审报告为单一信源（DevProjectTeamSkill 侧不保留实现）。