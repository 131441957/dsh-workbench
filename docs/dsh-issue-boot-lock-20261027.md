# [bug] desktop boot 被残留写锁卡死：`atomic-write: timed out waiting for the writer lock at …\community\installation-v1.json.lock`，必须手删锁才能启动

> 一份可独立提交的 issue 报告（与 meow-memory 无关，属 DSH 桌面端 / `@deepseek-ai/dsh-atomic-write`）。

## 摘要

`E:\DSH\home\desktop\community\installation-v1.json` 的跨进程写锁在**内容为空或只写了一半**时永远不会被判为"持有者已死"，
于是启动流程等满超时后直接失败，用户必须手动删除隐藏路径下的 `.lock` 才能启动 DSH。已在 npm 最新版 `dsh-atomic-write@0.2.1-rc.4`
上复现同样的行为。

## 环境

| 项 | 值 |
|---|---|
| 应用 | DeepSeek Harness 桌面版（Windows 11） |
| 运行时 | `@deepseek-ai/dsh-desktop-runtime` 0.2.1-alpha.1（`E:\SSS\resources\app.asar\dsh\package.json`） |
| 相关包 | `@deepseek-ai/dsh-atomic-write` **0.2.1-alpha.1**（包内 `lib/index.js`，9095 字节，位于 `app.asar/dsh/node_modules/@deepseek-ai/dsh-atomic-write/`） |
| 数据目录 | `E:\DSH\home`（`DSH_HOME`） |
| 复现用 Node | v24.22.0（只用 npm 包本体，不涉及 DSH 进程） |

## 现象

启动时渲染进程报错，界面起不来：

```
Error: Error invoking remote method 'dsh-desktop:boot': Error: atomic-write: timed out
waiting for the writer lock at E:\DSH\home\desktop\community\installation-v1.json.lock
    at … index-DWdEYI27.js:126
```

- 运行时日志：`E:\DSH\home\desktop\community\runtime-log-v1.json`，条目时间 `2026-10-27T02:17:10.215Z`（本地 10:17）
- **不是等一会儿就好**：重启无效，DSH 完全无法启动
- 手动删除 `E:\DSH\home\desktop\community\installation-v1.json.lock` 后才能正常启动
- 事后该目录只剩 `runtime-log-v1.json`，`installation-v1.json` 与 `.lock` 均不存在

## 最小复现（不需要启动 DSH）

```js
import { withFileLock } from '@deepseek-ai/dsh-atomic-write'
import { writeFile, rm } from 'node:fs/promises'

const target = '<任意目录>/installation-v1.json'
const lock = target + '.lock'

// 制造"进程在 wx 创建后、写入 pid 前被杀"的残留锁
await rm(lock, { force: true })
await writeFile(lock, '', { mode: 0o600 })

try {
  await withFileLock(target, async () => 'ok', { waitMs: 300 })
  console.log('took over')
} catch (error) {
  console.log('failed:', error.message)
}
// => failed: atomic-write: timed out waiting for the writer lock at <...>/installation-v1.json.lock
```

实测结果（`dsh-atomic-write@0.2.1-alpha.1` 与 **0.2.1-rc.4** 结果一致）：

| 锁文件内容 | 结果 |
|---|---|
| 不存在 | 立即获取（基线） |
| **0 字节（空）** | **超时抛错，锁保留** ← 本次事故形态 |
| `12345`（无换行） | **超时抛错，锁保留** |
| `999999\n`（该 PID 不存在） | 立即接管成功 |
| `<自己 PID>\n` | 超时抛错，锁保留 |
| `<无关活着的 PID>\n` | 超时抛错，锁保留 |

## 根因

`@deepseek-ai/dsh-atomic-write` 的 `withFileLock()`：

```js
await writeFile(lockPath, `${process.pid}\n`, { mode: 0o600, flag: 'wx' })   // 先创建、再写入
...
} else if (await takeOverExitedLock(lockPath)) continue
if (Date.now() >= deadline) throw new Error(`atomic-write: timed out waiting for the writer lock at ${lockPath}`)
```

接管判定：

```js
/** Whether the holder a `<pid>\n` record names is proven gone */
function holderExited(record) {
  if (!/^\d+\n$/.test(record)) return false        // ← 空/半写记录直接判为"无法证明已死"
  const pid = Number(record.trim())
  if (pid === 0 || pid > 2147483647) return false
  if (pid === process.pid) return false
  try { process.kill(pid, 0); return false } catch (error) { return error.code === 'ESRCH' }
}
```

问题有三层：

1. **空锁 / 半写锁永不接管**：`wx` 创建与 `writeFile` 写入内容不是同一个原子动作，进程在两者之间被强杀（任务管理器结束、
   崩溃、断电）就留下 0 字节或残缺的 `.lock`；`holderExited()` 对不匹配 `^\d+\n$` 的记录一律返回 `false`，
   `takeOverExitedLock()` 于是直接放弃，进入"等满 deadline 再说"的死路。
2. **deadline 到了只抛错，不尝试清理**：默认 `DEFAULT_LOCK_WAIT_MS = 2000`，超时后锁原样保留，下次启动再踩一次，形成持久死锁。
3. **PID 复用无解**：包内注释自己承认 —— "A holder whose PID a live process reused keeps its lock until an operator removes it"，
   记录里只有 pid，没有进程启动时间，无法区分"同一个 PID 的另一个进程"。（这与本次现象不冲突，但同属一类不可自愈的残留锁。）

## 影响

- 启动路径上的单点故障，直接表现为"DSH 打不开"，且报错信息只有一个路径，用户很难想到要手删隐藏目录里的锁；
- 用户若不知道 `E:\DSH\home\desktop\community\` 这个位置，等于软件彻底不可用。

## 建议修法

1. **让"无法证明持有者活着"的锁可以过期**：对 0 字节 / 不匹配 `^\d+\n$` / 记录 pid 非法的锁，按文件 mtime 给一个宽限期
   （如 30s），超期即视为陈旧并可接管（接管前仍走现有的 claim 文件串行化，避免误删别人刚拿到的锁）。
2. **记录里带上进程身份**：写 `<pid>:<processStartTime>`（Windows 可用 `GetProcessTimes`/`wmic` 等价信息，POSIX 用
   `/proc/<pid>/stat` 的 starttime），接管时比对"同一 pid 且同一启动时间"，彻底解决 PID 复用。
3. **超时前做最后清理尝试**：`deadline` 到达时先做一次 `stale` 判定 + 接管，再决定抛错；并在错误信息里附上
   "检测到残留锁 <path>，可安全删除"这类可操作提示。
4. **boot 路径显式指定 `waitMs` 并带可读的失败提示**：`installation-v1.json` 的写入属于启动关键路径，2s 太紧；
   失败时最好由桌面端弹一个"清除残留锁并重试"的按钮，而不是把裸错误抛到渲染进程。

## 临时绕过（当前版本）

```powershell
Remove-Item 'E:\DSH\home\desktop\community\installation-v1.json.lock' -Force
```

删完直接启动即可（本次事故就是这么恢复的）。

## 版本核对

- 本机打包：`dsh-atomic-write@0.2.1-alpha.1`
- npm 最新：`0.2.1-rc.4`（2026-08-10 发布）
- `0.2.1-rc.4` 与 `0.2.1-alpha.1` 的差异只有 AbortSignal 支持（`setTimeout(..., { signal })` + `throwIfAborted()`）；
  `holderExited()` 的 `^\d+\n$` 判定与接管流程**完全未变**，上述复现表在 rc.4 上实测同样成立 → **截至 rc.4 未修复**。
