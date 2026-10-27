# E:\SOS（官方 0.2.1-rc.3）启动失败 · 诊断记录

- 日期：2026-10-27
- 现象：用户无法启动 `E:\SOS`（官方 0.2.1-rc.3），因此无法测试最新版；GitHub issue 提示可能是 cookie 过多。
- 结论：**两个独立原因叠在一起**，一个是设计行为、一个是真故障。

## 1. 主驾在跑时，SOS 必然秒退（设计行为）

证据：

- `E:\SOS\resources\app.asar` 里 `claimDesktopSingleInstance()`：`if (!application.requestSingleInstanceLock()) { application.quit(); return false }`
- 两个安装共用同一个 Electron 数据目录 `%APPDATA%\@deepseek-ai\dsh-desktop` → 单实例锁互斥
- 实测：主驾（`E:\SSS`，pid 2400/9344/13128…）在跑时启动 SOS → **立刻退出、无 stderr、无崩溃日志、无新窗口**
- `--user-data-dir` 各种写法都被它自己的参数校验拒掉（`bad option: --user-data-dir`），所以没法给 SOS 单独 profile

**含义**：想测最新版，必须先把主驾完全退出（含托盘）。

## 2. 主驾关闭时，welcome 认证失败（真故障）

`%APPDATA%\@deepseek-ai\dsh-desktop\logs\crash-2026-10-27T02-13-31-340Z-host.log`（10:13 本地）：

```
app: @deepseek-ai/dsh-desktop 0.2.1-rc.3
Error: desktop welcome: Web authentication failed
    at connectDesktopWelcome (file:///E:/SOS/resources/app.asar/lib/main.js:8886:31)
```

对应代码（asar 内 `lib/types/welcome-backend.js`）：

```js
async function connectDesktopWelcome(authenticatedUrl, send, cookies = () => Promise.resolve("")) {
  const origin = new URL(authenticatedUrl).origin
  const authenticated = await send(authenticatedUrl, { credentials: "include" })
  await authenticated.body?.cancel()
  if (!authenticated.ok) throw new Error("desktop welcome: Web authentication failed")
```

即：带 cookie 请求本机 launch URL，**只要响应不是 2xx 就报这句**。DSH 每次启动都会发一枚 `dsh-auth-<随机>` cookie，而 **cookie 不按端口隔离**（同一 `127.0.0.1` 的所有安装/所有次启动都堆在一个 host 下），越攒越多的请求头最终会顶到 Node 的 16KB 头上限 → 431/401 → 正是这句报错。这与 GitHub issue 说的「cookie 过多」吻合。

现场数据：`Network\Cookies` 52 KB（库被运行中的进程独占，读不了；`esenttutil`/共享读都被拒）。

## 3. 修复脚本（已写并演练）

`tools\fix-sos-start.ps1`：

1. 检查是否还有 DeepSeek Harness 进程 → 有就提示先完全退出
2. 备份 `Cookies` / `Cookies-journal` / `Local State` 到 `backups\sos-cookie-fix-<时间>\`
3. 只清理 `dsh-auth*` cookie，**每个 host 保留最新 N 条**（默认 5），其它 cookie 一条不动，然后 VACUUM
4. 可选 `-Launch`：用独立 home `E:\SOS-test\home` 启动 SOS（不碰主驾 home），并检查是否起来

用法：

```powershell
# 干跑（只统计，不改）
powershell -ExecutionPolicy Bypass -File E:\DSH-WORKBENCH\tools\fix-sos-start.ps1 -WhatIf
# 清理
powershell -ExecutionPolicy Bypass -File E:\DSH-WORKBENCH\tools\fix-sos-start.ps1
# 清理并启动 SOS
powershell -ExecutionPolicy Bypass -File E:\DSH-WORKBENCH\tools\fix-sos-start.ps1 -Launch
```

**演练记录**（用合成 Cookies 库，Chromium 表结构，12 条 `dsh-auth` + 2 条其它）：
`-CookieDb <合成库> -KeepNewest 5` → 14 条变 7 条，保留最新 5 条（`dsh-auth-07..11`），`dsh-keep` 与 `example.com` 的 cookie 原样未动。

## 4. 还没做的（需要主驾关闭）

真实 cookie 库的统计与清理、以及清理后 SOS 能否真正启动，都必须在**主驾完全退出**后才能验证——而主驾就是当前聊天所在的进程，所以这一步要用户配合。

## 5. 顺带发现的另一个问题（主驾侧）

`logs\crash-2026-10-27T02-17-10-216Z-web-boot.log`（10:17，来自 `E:/SSS` 0.2.1-alpha.1）：

```
Error: atomic-write: timed out waiting for the writer lock at E:\DSH\home\desktop\community\installation-v1.json.lock
```

即主驾也曾因**残留写锁**起不来（与之前记录过的 atomic-write 锁 bug 一致）。若再现，删掉那个 `.lock` 即可。
