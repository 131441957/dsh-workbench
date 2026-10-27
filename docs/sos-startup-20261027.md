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

## 3. 隔离：能隔离什么、不能隔离什么（2026-10-27 更正）

**先纠正一处**：最初的修复脚本只设了 `DSH_HOME`，**没有隔离 Electron profile**；而且那两次启动都死在单实例锁上，`DSH_HOME` 其实从未被真正使用（测试目录为空，后来还被清理掉了，连"没写入"的现场也没留）。所以「用它的隔离 home，不碰主驾 home」这句话当时说过头了。

| 状态 | 位置 | 能否隔离 | 依据 |
|---|---|---|---|
| Harness home（sessions/profiles/插件 link） | `$DSH_HOME`（用户变量 = `E:\DSH\home`） | **能**（环境变量覆盖） | asar 内文档：`@deepseek-ai/dsh-home-paths` 解析 `$DSH_HOME` 或 `~/.dsh` |
| Electron profile（Cookies / localStorage / **单实例锁**） | `%APPDATA%\@deepseek-ai\dsh-desktop` | **不能并行隔离**，只能换目录 | `claimDesktopSingleInstance()` 用 `requestSingleInstanceLock()`；`--user-data-dir` 被它自己的参数校验拒绝 |

所以：**两者不能同时运行**。真要测 rc.3，得把主驾（以及工作台那份 `E:\DSH-WORKBENCH\app`）都退掉，再把 profile 目录换出去。

这条不能省，因为「跨版本共用 home」已经造成过实际损失：2026-10-26 用 alpha.1（`E:\SSS`）去启动 rc.3 建好的 home，结果 profile 被重建、bundles 被重置、link 安装的插件目录被清空。

## 4. 修复脚本（已改为真隔离，2026-10-27 重写）

`tools\fix-sos-start.ps1`：

| 参数 | 作用 |
|---|---|
| `-Status`（默认） | 打印现状：在跑的 Harness、`DSH_HOME`、profile 是否被换出、独立 home 是否存在 |
| `-Isolate` | 检查进程 → 备份 profile 到 `backups\sos-isolate-<时间>\` → 把 `dsh-desktop` 改名 `dsh-desktop.main-backup` → 用 `DSH_HOME=E:\SOS-home` 启动 SOS（全新 profile，无累积 cookie） |
| `-Restore` | SOS 退出后，把 SOS 生成的 profile 留作 `dsh-desktop.rc3`，把 `dsh-desktop.main-backup` 换回 `dsh-desktop` |
| `-CleanCookies` | 不隔离、只清 `dsh-auth*`（每个 host 保留最新 N 条）——会同时影响主驾登录态 |
| `-WhatIf` | 只演练不动手 |

实测（2026-10-27）：
- `-Status` 正确列出 8 个 Harness 进程（`E:\SSS` 与 `E:\DSH-WORKBENCH\app` 两处）
- `-Isolate -WhatIf` 在检测到进程后拒绝执行，并打印完整计划（备份路径、改名目标、启动用的 `DSH_HOME`）
- 只清 cookie 的逻辑用合成 Chromium Cookies 库演练过：14 条 → 7 条，保留最新 5 条 `dsh-auth`，其它 cookie 未动

## 5. 还没做的（需要主驾关闭）

真实 cookie 统计、清理，以及隔离启动后 rc.3 能否真正起来——都要在主驾关闭后做（主驾就是当前聊天所在的进程）。

## 5. 顺带发现的另一个问题（主驾侧）

`logs\crash-2026-10-27T02-17-10-216Z-web-boot.log`（10:17，来自 `E:/SSS` 0.2.1-alpha.1）：

```
Error: atomic-write: timed out waiting for the writer lock at E:\DSH\home\desktop\community\installation-v1.json.lock
```

即主驾也曾因**残留写锁**起不来（与之前记录过的 atomic-write 锁 bug 一致）。若再现，删掉那个 `.lock` 即可。
