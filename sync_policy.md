# dev-git-hub 同步策略

> 定位：日常高频 push 走 LAN（秒级、无 WAN 抖动），GitHub/Gitee 退为异步灾备；Windows 副本全量备份。
> 与 DevProjectTeamSkill 现状衔接：技能库仍以 GitHub(origin)+Gitee(mirror) 为权威，LAN 是「快速中转」非唯一权威（防单点）。

## 一、同步矩阵

| 场景 | 动作 | 目标 | 频次 |
|------|------|------|------|
| 日常提交 | `git push hub main` | LAN 中枢（Mac） | 每次提交后 |
| Windows 同步 | `git pull hub main`（Dell） | Windows 副本 | 工作切换时 |
| WAN 灾备 | `mirror_push`（origin+mirror） | GitHub + Gitee | weekly 或发布前 |
| 断网可用 | Windows 副本本地工作 | 本地 | 任一时 | 
| LAN 不可用 | WAN 双推兜底 | GitHub + Gitee | 即时 |

## 二、WAN 灾备策略（对齐现有 mirror_push 熔断）

- 灾备沿用现有 `mirror_push.py`（已有熔断：凭据失败置阻断/网络失败置冷却，自动真实 IP 回退）
- LAN push 成功 ≠ 灾备完成——WAN 灾备独立按 cadence 执行（`config.yaml` 中 `wan.sync_cadence`）

## 三、反信号（防过度工程，与 DevProjectTeamSkill 铁律#16 对齐）

| 反信号 | 判定 | 动作 |
|--------|------|------|
| LAN push 未成常态 | 2 阶段内（观察期）`git push hub` 调用 <3 次 | 撤回 LAN，仅保留 WAN 双推 |
| Mac 长期关机/断网 | 中枢不可用持续 >7 天 | 以 Windows 副本 + WAN 兜底，暂缓 LAN |
| WAN 连续失败过多 | >2 次/会话 | 触发镜像熔断冷却（现有机制） |

## 四、解耦原则（换机器不改结构）

- 所有 IP/路径/用户/端口 → `config.example.yaml` → 复制为 `config.yaml` 按实修改
- 新仓库：`hub_name` 加一行 + `git remote add hub`；结构不变
- 换 SSH 密钥：只改 `authorized_keys` + hub 端配置，不动项目代码

**最后更新**：2026-08-30（初始创建）