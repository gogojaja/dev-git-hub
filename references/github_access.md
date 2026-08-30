# GitHub 访问异常处理规则

> 适用：GitHub 提交失败时的 DNS/代理/远端访问诊断。最常见根因是 DNS 失效导致解析到错误 IP，或代理链路被污染，不能访问远端环境。
> 结论：在技能中尽可能多地保留真实 IP 记录，是处理该问题的有效手段；优先使用已验证的候选 IP 作为临时 DNS 回退。
> 故障现象：`Failed to connect` / `Could not connect` / `Recv failure: Connection was reset` / `nc: connection failed, SOCKS error 2`。

## 1. 真实 IP 备份机制（优先级）

GitHub 访问失败时，不能只停留在“重试网络”，必须优先判定是否为 DNS 实效。处理顺序如下：

1. 先检查 `git remote -v` 与 `env | grep -Ei 'http|https|proxy|socks'`，确认是否被代理或 SOCKS 兜底污染；
2. 再读取 `docs/github_ip_records.csv`，按真实 IP 作为备用解析目标；
3. 对 `github.com`、`api.github.com`、`raw.githubusercontent.com`、`github.io` 等域名做一轮 `--resolve` 或 `hosts` 映射；
4. 如果网络仍失败，切换到 VPN / 代理 / 跨境网络后再重试；
5. 所有变更必须保留在本地日志与台账中，避免重复踩坑。

完整 DNS 资源记录见项目 `docs/github_ip_records.csv`（含 api/ssh/gist/raw/pages/Fastly CDN 等子域）。

### github.com 主站（当前解析）
```
20.205.243.166    ← 多 DNS 服务器确认（8.8.8.8/1.1.1.1/208.67.222.222）
```

### github.com 历史可达 IP（AS36459 140.82.112.0/20）
```
140.82.112.4      ← 已验
140.82.113.4      ← corpus.lantern.io 记录
140.82.114.4      ← 已验
140.82.121.4      ← 已验
```

### GitHub Pages / assets-cdn（AS36459 185.199.108.0/22）
```
185.199.108.153   ← github.io / assets-cdn
185.199.109.153
185.199.110.153
185.199.111.153
```

### raw.githubusercontent.com / github.map.fastly.net（Camo/头像/媒体 CDN）
```
185.199.108.133   ← raw / camo / avatars
185.199.109.133
185.199.110.133
185.199.111.133
```

### github.global.ssl.fastly.net（Fastly 全局 CDN）
```
162.125.34.133    ← DNS 确认
```

### Fastly 公网 IP 段（assets-cdn 走 Fastly）
```
23.235.32.0/20    151.101.0.0/16    199.232.0.0/16    146.75.0.0/17
104.156.80.0/20   140.248.64.0/18   185.31.16.0/22
```

## 2. 连通性验证流程

```powershell
# 1) 先清理代理和代理变量，避免 SOCKS/HTTP 代理把真实 GitHub IP 访问链路拦住
Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:ALL_PROXY -ErrorAction SilentlyContinue

# 2) 逐个测试候选 IP（超时 8 秒）
$ips = @("20.205.243.166","140.82.112.4","140.82.113.4","140.82.114.4","140.82.121.4","185.199.108.153","162.125.34.133")
foreach ($ip in $ips) {
  $r = curl.exe -s -o NUL -w "%{http_code}" --connect-timeout 8 --resolve github.com:443:$ip https://github.com
  Write-Output "$ip -> $r"
}
```

```powershell
# 3) 刷新本地 DNS 缓存
ipconfig /flushdns
```

```powershell
# 4) 如全部不可达，直接用真实 IP 进行一次强制解析验证
curl.exe -s --resolve github.com:443:140.82.112.4 https://github.com
curl.exe -s --resolve github.com:443:20.205.243.166 https://github.com
```

```powershell
# 5) 备用方案：将真实 IP 写入 hosts（仅在确认为 DNS 实效且用户授权后执行）
$ip = "20.205.243.166"
"$ip github.com" | Out-File -Append -Encoding ascii "$env:SystemRoot\System32\drivers\etc\hosts"
```

> 注意：仅在用户明确授权且环境允许时修改 hosts；未授权时优先使用 `--resolve` 进行临时回退，不直接写系统文件。

## 3. push 需带凭据 token

fine-grained PAT（Contents read/write；token 由用户提供，勿硬编码入库）：

```powershell
$url="https://gogojaja:<token>@github.com/gogojaja/DevProjectTeamSkill.git"
git remote set-url origin $url        # 临时带凭据
git push origin main
git remote set-url origin "https://github.com/gogojaja/DevProjectTeamSkill.git"  # 用完还原
```

> PowerShell 拼接 `https://user:token@host/path` 直传会损坏 URL，必须经 `git remote set-url` 传参。

## 4. 失败闭环：DNS 实效 → IP 回退 → 代理清理 → 重试

1. 先判断失败日志：`Socks error`、`connection failed`、`Could not connect` 一般属于代理或 DNS 链路错误；
2. 读取 `docs/github_ip_records.csv`，确认当前/历史真实 IP；
3. 使用 `curl --resolve github.com:443:<ip> https://github.com` 做最小验证；
4. 如验证通过，则临时设置 `git remote set-url` 或 `git config` 继续推送；
5. 若验证失败，记录失败日志和已测试 IP，等待 VPN/代理修复或更稳定网络；
6. 推送成功后执行 `git rev-parse HEAD origin/main`，确保本地提交与远端一致；
7. 若失败仍在代理链路，清理 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 变量，避免 SOCKS 兜底导致被运维网络干扰。

## 5. 其他故障处理

- `api.github.com` 偶发 CRL 离线（`CRYPT_E_REVOCATION_OFFLINE`）为瞬时网络问题，重试即可。
- `git push` 失败的最常见根因是 DNS 实效，尤其在代理或网络环境重置后，经常解析到失效 IP；
- 真实 IP 记录越多，越容易在恶劣网络环境中快速恢复；
- 全部 IP 不可达时，建议用户使用 VPN/代理打通 GitHub 后再操作。

## 6. 数据来源

- DNS 解析：`nslookup -type=A github.com 8.8.8.8` / `1.1.1.1` / `208.67.222.222`
- GitHub Meta API：`https://api.github.com/meta`（返回完整服务 IP 段）
- Fastly 公网 IP：`https://api.fastly.com/public-ip-list`
- 社区记录：`docs/github_ip_records.csv`（含历史 IP、各子域、Fastly CDN 节点）

---

**文档版本**：v1.0.0
**最后更新**：2026-08-10
