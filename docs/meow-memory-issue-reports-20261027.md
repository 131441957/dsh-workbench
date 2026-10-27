# meow-memory 两个客户端 bug 的 issue 稿（2026-10-27）

环境（两个 issue 通用）

- DSH：DeepSeek Harness 桌面版，`@deepseek-ai/dsh-desktop-runtime` 0.2.1-alpha.1，Windows 11，Web 渲染进程（`dsh-app://app/assets/index-DWdEYI27.js`）
- meow-memory：本机装的是 0.31.1；**0.32.0 / 0.32.1（npm latest，2026-10-26T14:27:49Z 发布）与 GitHub `main`（最后提交 `7e53a81`，2026-10-26T14:25:09Z）均已复核，两个 bug 都还在**：
  - 三个已发布版本的 `lib/client.js` 完全一致 —— SHA256 `1BCB063B74F6A0E28ECF7082B30FA586CA74A9769286070DF5BFFB93E5401720`，141485 字节；
  - `main` 的 `src/client-fold.ts:271-278` 仍是 `block.argsRaw` + `args.length`；`src/settings-page.ts:743` 仍是 `onUiLocaleChange(registerSection)`；
  - 0.32.1 只动了 host 侧（`lib/index.js` 哈希变了），客户端 bundle 没重新构建；
  - 现有 issue 里没有重复项（#78 是同类"slot 注册失败"但不同点，已 closed）。
- 日志来源：`E:\DSH\home\desktop\community\runtime-log-v1.json`（桌面端运行时日志，entries 上限 36）

---

## Issue 1：每次加载界面都会报 `slot "settings.section" is not declared`

**标题建议**：`[bug] 每次客户端加载都刷一条 error：UI 语言订阅者异常 slot "settings.section" is not declared`

### 现象

每次刷新/启动界面，运行时日志固定出现一条 error（渲染进程 console 同样可见）：

```
[meow-memory] UI 语言订阅者异常： Error: slot "settings.section" is not declared (a parent entry's children table must declare it)
    at hh.register (dsh-app://app/assets/index-DWdEYI27.js:56:72232)
    at Proxy._register (...)
    at registerSection (…meow-memory/client.js…:2460:32)
    at onUiLocaleChange (…meow-memory/client.js…:546:5)
    at mountWithScope (…meow-memory/client.js…:2472:31)
    at attach (…meow-memory/client.js…:2500:21)
    at applySettingsPage (…meow-memory/client.js…:2503:3)
```

2026-10-26 一天内复现 11 次（10:12 / 10:42 / 11:40 / 12:28 / 12:32 / 12:43 / 12:55 / 13:01 / 14:15 / 14:41 / 次日 02:18），每次对应一次界面加载。

### 复现

1. 安装并启用 meow-memory（0.31.1 或 0.32.0）
2. 重新加载界面（DSH 桌面端没有浏览器式 F5：改插件文件后由 `dsh-client-hmr` 自动热加载；手动手段是重开应用/从应用菜单重新加载）
3. 看运行时日志或 DevTools console → 必现一条上述 error

### 根因

`applySettingsPage()` 里：

```ts
const disposeInjection = ctx.slots.inject('settings.section', registerSection)
const unsubscribeLocale = onUiLocaleChange(registerSection)   // ← 订阅时会同步回调一次
```

而 `onUiLocaleChange()`（`lib/client.js:543-553`）在 `listeners.add(fn)` 之后会**立刻** `fn(active)` 跑一次。
这一瞬间外壳 `ui-settings` 还没在 `sidebar.settings` 的 children 表里声明 `settings.section`，
`ctx.slots.register({ name: 'settings.section', … })` 直接抛
`slot "settings.section" is not declared`；异常被语言订阅者的兜底 `catch` 接住，于是打成一条 error。

真正能用的注册随后由 `ctx.slots.inject()` 的回调补上，所以**设置页本身是好的**，只是每次加载必刷红字。
另外还有个潜在坑：`registerSection()` 是「先 dispose 旧条目再注册新条目」，语言切换时若插槽恰好不可用，
注册抛错后 `disposeEntry` 已被置空，条目就丢了（失败路径没有回滚）。

### 建议修法

以 `inject` 回调作为「插槽确实就绪」的信号；语言变化只做重注册，且在就绪前直接跳过；注册失败只记 info：

```ts
let slotReady = false
const registerSection = (): void => {
  try { disposeEntry?.() } catch { /* 旧条目已在卸载 */ }
  disposeEntry = null
  try {
    disposeEntry = ctx.slots.register(
      { name: 'settings.section', id: SETTINGS_NS, order: 35, label: () => t('settings.title'), inject: () => ({ scope }) },
      MemorySettingsSection,
    )
  } catch (error) {
    console.info('[meow-memory] settings.section 尚未声明，跳过本次注册（插槽就绪后自动重试）：',
      error instanceof Error ? error.message : String(error))
  }
}
const disposeInjection = ctx.slots.inject('settings.section', () => { slotReady = true; registerSection() })
const unsubscribeLocale = onUiLocaleChange(() => { if (!slotReady) return; registerSection() })
```

本机已验证：改后界面自动热加载（无需刷新），日志零新增；`settings.section` 占位者仍为 `meow-memory / order 35 / active`。

---

## Issue 2：展开记忆折叠卡片时 `toolCallDetail` 崩掉 `conversation.composer.dock` 槽位

**标题建议**：`[bug] toolCallDetail 缺 argsRaw 时读 undefined.length，展开折叠卡片会把 conversation.composer.dock 槽位炸掉`

### 现象

运行时日志两条连着的 error：

```
TypeError: Cannot read properties of undefined (reading 'length')
    at toolCallDetail (…meow-memory/client.js…:819:15)
    at enhanceClone (…meow-memory/client.js…:2735:20)
    at fillBody (…meow-memory/client.js…:2770:7)
    at applyFoldState (…meow-memory/client.js…:2923:45)

slot entry crashed in 'conversation.composer.dock': TypeError: Cannot read properties of undefined (reading 'length')
```

关键点：这不是「详情显示不出来」这种小事 —— 异常抛进了 slot 渲染，外壳按槽位崩溃处理，
**当场把 `conversation.composer.dock` 上的记忆折叠 dock 拆掉**（用户侧表现为记忆折叠条整块消失）。

### 复现

1. 会话里存在被折叠的 meow-memory 反思轮（横条状态如「已注入记忆 / 反思完成」）
2. 展开该折叠卡片（触发 `fillBody()` 克隆原始行 → `enhanceClone()` 增强详情）
3. 只要被折叠的轮次里存在「有 `name` 但没有 `argsRaw`」的 tool-call 节点，必崩（一次 14:45:40 实测）

### 根因

`enhanceClone()` 的 tool-call 分支：

```ts
const name = 'name' in root ? root.name : (root.call?.name ?? root.callId)
const argsRaw = 'name' in root ? root.argsRaw : (root.call?.argsRaw ?? '')   // ← 可能 undefined
const detail = toolCallDetail({ name, argsRaw })
```

`'name' in root` 成立（RunningToolCall 形状，自带 `name`），但对象上没有 `argsRaw` 时 `argsRaw` 就是 `undefined`。
`toolCallDetail()` 里：

```ts
export function toolCallDetail(block: { name: string; argsRaw: string }): string {
  let args = block.argsRaw
  try { args = JSON.stringify(JSON.parse(block.argsRaw), null, 2) } catch {}
  return args.length > 0 ? `${block.name}\n${args}` : block.name   // ← 819:15，undefined.length
}
```

为什么类型检查没拦住：`node.data` 是 `as ToolChatData` / `as AssistantChatData` 硬转，
而产物由 esbuild 打包（不做类型检查），所以签名要求 `argsRaw: string` 也只是纸面约定。
同类风险还有 `enhanceClone()` 的 assistant-step 分支，它把 block 原样丢给 `toolCallDetail(block)`，
而这类块的参数可能叫 `args` / `arguments`（宿主 wire 记录里就是 `arguments` 字符串/对象），同样没有 `argsRaw`。

### 建议修法

取参按多个字段名兜底、多位置兜底，并容忍对象参数；缺失时退化为「只显示工具名」，绝不抛：

```ts
function argsFieldOf(record: unknown): unknown {
  if (record === null || record === undefined) return undefined
  const s = record as { argsRaw?: unknown; arguments?: unknown; args?: unknown; input?: unknown }
  return s.argsRaw ?? s.arguments ?? s.args ?? s.input
}
function toolArgsOf(record: unknown): unknown {
  for (const c of [record, (record as any)?.root, (record as any)?.call, (record as any)?.root?.call]) {
    const v = argsFieldOf(c)
    if (v !== undefined) return v
  }
  return ''
}
export function toolCallDetail(block: { name?: string; argsRaw?: unknown; root?: unknown; call?: unknown }): string {
  const raw = toolArgsOf(block)
  let args: string
  if (typeof raw === 'string') {
    args = raw
    try { args = JSON.stringify(JSON.parse(raw), null, 2) } catch { /* 非 JSON 原样展示 */ }
  } else {
    try { args = raw === null || raw === undefined ? '' : (JSON.stringify(raw, null, 2) ?? '') }
    catch { args = String(raw) }
  }
  const name = block?.name ?? ''
  return args.length > 0 ? `${name}\n${args}` : name
}
```

调用点改成传整份 `root`，让兜底逻辑能看见 `root.call`：

```ts
const detail = toolCallDetail({ name, root })
```

本机已验证：从补丁后的产物里抽出真实函数做单测，覆盖 10 种参数形状（含无参、`undefined`、`null`、
`arguments` 字符串、`args` 对象、`call.argsRaw` / `call.arguments` / `root` 包装）→ 全部不抛且详情正确。

---

## Issue 3（DSH 内核，不是 meow-memory）：残留 `installation-v1.json.lock` 让 DSH 起不来

> 独立完整稿（含可运行复现、源码定位、rc.4 版本核对）：`dsh-issue-boot-lock-20261027.md`。
> 下面只是概要，正式提交请用那份。

**标题建议**：`[bug] desktop boot 被残留写锁卡死：atomic-write: timed out waiting for the writer lock at …\community\installation-v1.json.lock，必须手删锁才能启动`

### 现象

桌面端启动时整个界面起不来，渲染进程报：

```
Error: Error invoking remote method 'dsh-desktop:boot': Error: atomic-write: timed out
waiting for the writer lock at E:\DSH\home\desktop\community\installation-v1.json.lock
```

（`E:\DSH\home\desktop\community\runtime-log-v1.json`，2026-10-27 02:17:10Z = 本地 10:17 记录到 1 次）

### 实际后果

- 不是"等一下就好"：**DSH 完全无法启动**，重启也无效；
- 用户手动删除 `E:\DSH\home\desktop\community\installation-v1.json.lock` 之后才能正常启动；
- 该目录事后只剩 `runtime-log-v1.json`，`installation-v1.json` 本体与 `.lock` 都不在了。

### 推测成因（待维护者确认）

`installation-v1.json` 的原子写在进程被强杀（任务管理器结束进程 / 崩溃 / 断电）时留下了 `.lock`，
下次启动的 writer 只做"等锁 + 超时"，没有 owner/过期抢占逻辑，于是直接放弃并让 boot 失败。

### 建议

1. 锁文件写入 owner（pid + 启动时间戳），发现 owner 进程不存在或超过 TTL 就直接抢占，而不是干等超时；
2. boot 失败时不要只吐异常：在日志/弹窗里给出可操作提示（"检测到残留锁 <path>，是否清除并重试"），
   别让用户自己去 `E:\DSH\home\desktop\community\` 里找隐藏文件；
3. `writeFileAtomic` 的锁超时建议回落到"无锁写入 + 原子 rename"或至少带一次重试，避免单点把整个 boot 打死。

### 附：这条别当 bug 报

- `[connection] connection lost, retry #1`：正常断线重连。
