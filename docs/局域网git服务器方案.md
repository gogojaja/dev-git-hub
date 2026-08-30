# 局域网 git 服务器拓扑方案（v1）

> **决策对象**：DevProjectTeamSkill 仓库 git 管理优化——Mac mini 作 LAN git 服务器 + Windows 全量副本，减少频繁远端提交
>
> **档位**：FULL（网络拓扑架构级/跨机器协同）
>
> **证据卡**：`docs/evidence_cards_局域网git服务器_20260829.json`（EV-201~207）
>
> **评审报告**：`docs/reviews/评审报告_局域网git服务器_v1_多视角评审.csv`
>
> **评审模式**：多视角自评（非真实第三方）＋真实外部信号（git 官方 bare-repo 工作流标准 + 本机实测 SSH/git 版本）+ 反信号（DORA 单点风险）

---

## ✅ 可稳定达成效果

### 1. 目标（减少频繁远端提交）

当前远端推送 GitHub 网络不稳（今日多次 30s 超时 + 真实 IP 回退），频繁「提交→双推→重试」形成往返浪费。目标：**日常高频推 → 局域网中枢（快）**，GitHub/Gitee 退为**异步灾备**（仅发布/跨地同步时推）。

### 2. 拓扑设计（三层）

| 层 | 角色 | 说明 |
|----|------|------|
| **LAN 中枢** | Mac mini bare 仓库（`~/git/hub/dev-project-team-skill.git`） | 日常 push 主目标，LAN 毫秒级、无 WAN 抖动 |
| **Windows 副本** | Windows 全量克隆（`git clone` 自动含全部历史/分支） | 全量备份 + 断网可用 + 快速本地访问 |
| **WAN 灾备** | GitHub(origin) + Gitee(mirror) 保持 | 跨地/发布时双推，LAN 不可用时兜底 |

### 3. 实施步骤（M1~M4）

| 阶段 | 动作 | 说明 |
|------|------|------|
| **M1 Mac 建 bare 中枢** | `git init --bare ~/git/hub/dev-project-team-skill.git` | 标准 bare hub（EV-204） |
| **M2 SSH over LAN** | 启用 sshd + 密钥认证（禁密码） | git-over-SSH 标准协议（EV-203） |
| **M3 推入中枢** | 本地 `git remote add hub ssh://macmini/~/git/hub/...` + `git push hub --all` | 全量推（15MB） |
| **M4 Windows 克隆** | Windows `git clone ssh://macmini/~/git/hub/...` | 全量副本 = 自动备份（EV-202/205） |

### 4. 日常流程（优化后）

```
本地 → push hub（LAN，秒级）→ 定期 mirror_push（WAN 灾备，按需）
                              ↘ clone 到 Windows 副本（全量备份）
```

每日提交：`git push hub main`（LAN）替代频繁 `mirror_push`（WAN 重试）→ **消除网络等待往返**。

> **证据**：EV-201[high]（今日远端重试现状）、EV-203[high]（SSH 已装）、EV-205[medium]（LAN 消除 WAN 等待）、EV-204[high]（bare hub 标准）

---

## ⚠️ 理论最优效果与当前限制

| 限制/反信号 | 说明 | 缓解 |
|-------------|------|------|
| **LAN 单点**：Mac mini 关机/断网时中枢不可用 | 局域网服务器天然单点弱点（EV-206） | Windows 副本保留全量可离线工作；WAN 灾备兜底；中枢不是唯一权威 |
| SSH 配置复杂度 | git-over-SSH 需 SSH 密钥 + authorized_keys | 复用系统 sshd（已装），密钥认证两步完成 |
| 外部机器访问合规（铁律#7a） | Windows 副本属「项目外机器」 | 实施前需 `register_auth` 授权 Windows 机器 + 备份留痕 |
| 过度工程风险 | 若仅本地单机使用，LAN 中枢无增益 | 反信号：2 阶段内 LAN push 未成常态 → 撤回仅保留 WAN 双推 |

---

## 决策记录草案

- **标识**：ADR-2026-08-29-003（待架构角色正式编号）
- **决策**：构建「Mac mini LAN bare 中枢 + Windows 全量副本 + WAN 灾备维持」三层拓扑，日常高频 push 走 LAN，GitHub/Gitee 退为异步灾备
- **选项**：
  - A. 维持现状（仅 WAN 双推）→ 频繁 WAN 重试往返持续
  - B. **LAN 中枢 + Windows 副本（本方案）** → 日常快、灾备全、WAN 保留
  - C. 仅本地 bare（无 Windows 副本）→ 无异地备份、单点更高
  - D. 全部镜像到自建外部服务器 → 成本高、无必要
- **理由**：EV-201（远端不稳）+ EV-203（SSH 现成）+ EV-204（bare 标准）+ EV-205（LAN 快）
- **已验证**：git 2.50.1 + /usr/sbin/sshd 已装、仓库 15MB 小、LAN IP 192.168.3.86
- **不确定**：Windows 端实际克隆可达性（需 LAN 连通测试）
- **未关闭风险**：LAN 单点（Windows 副本 + WAN 灾备兜底）
- **反信号**：2 阶段内 LAN push 未成常态 → 撤回；Mac mini 长期关机则不可行

---

## 实施路线图

| 阶段 | 范围 | 交付物 | 门禁 |
|------|------|--------|------|
| **M1** | Mac bare 中枢 | `~/git/hub/dev-project-team-skill.git` | 创建成功 + push 全量 |
| **M2** | SSH over LAN | sshd 启用 + 密钥认证 | SSH 连通测试 |
| **M3** | 推入中枢 | remote hub + push --all | 与 origin 一致 |
| **M4** | Windows 克隆副本 | Windows 端全量克隆 | clone 完成 + 与 hub 一致 + 授权留痕 |

---

> **评审签署**：
> - Architect ⚠️ CHANGES_REQUESTED — 保留 WAN 灾备防单点（已并入 §2 三层拓扑）
> - SecurityReviewer ⚠️ CHANGES_REQUESTED — SSH 密钥认证 + Windows 机器授权（已并入 M2/M4）
> - Cost+演进 ⚠️ CHANGES_REQUESTED — 收益量化 + 外部机器合规（已并入 §4/反信号）
> **聚合决策**：🟡 **CHANGES_REQUESTED 收敛完成**（3 项 CR 全部并入方案）→ 待用户确认实施