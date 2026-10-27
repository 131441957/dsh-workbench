# meow-memory 客户端两处热修（2026-10-27）

来源：用户贴的 `C:\Users\Administrator\Desktop\dsh对话记录\dsh runting log.txt`（DSH 运行时日志导出，2026-10-26 08:27 ~ 2026-10-27 10:18）。

## 一、日志里到底有几件事

| # | 现象 | 频率 | 性质 |
|---|------|------|------|
| 1 | `[meow-memory] UI 语言订阅者异常：Error: slot "settings.section" is not declared (a parent entry's children table must declare it)` | 每次界面加载 1 条（10:12 / 10:42 / 11:40 / 12:28 / 12:32 / 12:43 / 12:55 / 13:01 / 14:15 / 14:41 / 02:18） | meow-memory 自身缺陷，噪音级 |
| 2 | `TypeError: Cannot read properties of undefined (reading 'length')` + `slot entry crashed in 'conversation.composer.dock'` | 14:45:40 一次 | meow-memory 真实崩溃：折叠卡片渲染把整个 dock 槽位炸掉 |
| 3 | `connection lost, retry #1` | 11:09 / 14:30 | 正常重连，非缺陷 |
| 4 | `dsh-desktop:boot … atomic-write: timed out waiting for the writer lock at …installation-v1.json.lock` | 02:17 一次 | **真问题（DSH 内核，非插件）**：残留写锁导致 DSH 起不来，用户手动删掉 `installation-v1.json.lock` 才启动。不是瞬时竞争、不会自愈 |

## 二、根因

### 1. 设置分区注册时序（日志 #1）

`lib/client.js: applySettingsPage() → mountWithScope()` 里：

```js
const disposeInjection = ctx.slots.inject('settings.section', registerSection)
const unsubscribeLocale = onUiLocaleChange(registerSection)   // ← 立刻同步回调一次
```

`onUiLocaleChange()`（`lib/client.js:543-553`）订阅时会**立即**用当前语言调用一次回调。此刻外壳的 `sidebar.settings`
还没声明 `settings.section`，`ctx.slots.register()` 直接抛 `slot ... is not declared`，异常被语言订阅者兜底 catch
后打成 `error` 日志。真正的注册随后靠 `inject` 回调补上——所以设置页本身一直是好的，只是每次加载刷一条红字。

### 2. 工具参数缺字段（日志 #2）

栈：`toolCallDetail (:819:15) ← enhanceClone (:2735:20) ← fillBody ← applyFoldState`，819:15 正是 `args.length`。

`enhanceClone()` 的 tool-call 分支构造的是 `{ name, argsRaw }`：

```js
const argsRaw = 'name' in root ? root.argsRaw : (root.call?.argsRaw ?? '')   // 可能 undefined
toolCallDetail({ name, argsRaw })                                            // → block.argsRaw.length 炸
```

`'name' in root` 成立（RunningToolCall 形状）但对象上没有 `argsRaw` 时，`argsRaw` 就是 `undefined`。
`toolCallDetail` 里 `let args = block.argsRaw` → `args.length` → TypeError。
TS 类型是 `as ToolChatData` 强转的，esbuild 又不做类型检查，所以编译期不会拦。
这个错不是"详情显示不全"，而是**异常抛进了 slot 渲染**——日志里紧跟着的
`slot entry crashed in 'conversation.composer.dock'` 说明折叠 dock 那一次被外壳当崩溃拆了。

## 三、改了什么（已落到本机运行副本）

改的是 profile 链接指向的安装副本：`E:\肥鱼工作区\_plugin-packages\meow-memory\lib\client.js`
（`E:\DSH\home\profiles\desktop\node_modules\meow-memory` → 该目录的 symlink，未动 profile 配置）。

备份：`E:\DSH-WORKBENCH\backups\meow-memory-client-20261027-102321\client.js(.map)`（141485 字节原件）

1. `mountWithScope()`：新增 `slotReady` 闸门 —— 只有 `inject` 回调（插槽确实就绪）之后才注册；
   注册包 try/catch，失败只 `console.info` 一行；语言切换时未就绪直接跳过。
2. `toolCallDetail()`：新增 `argsFieldOf()/toolArgsOf()`，按 `argsRaw → arguments → args → input`
   顺序取参，并在 `record / .root / .call / .root.call` 四个位置依次尝试；字符串走 JSON pretty，
   对象直接 `JSON.stringify`，缺失则退化为"只显示工具名"，并**只记一次** info 暴露真实字段名
   （`工具参数字段未知，详情降级为仅名称：<keys>`），方便日后定位。
3. `enhanceClone()` tool-call 分支：改传整份 `root`（`toolCallDetail({ name, root })`），不再在外层先拍平成 `argsRaw`。

体积 141485 → 142923 字节；`node --check` 通过。

## 四、验证

- 单元级：`tests/hotfix-check.cjs`（从打补丁后的 `lib/client.js` 里**抽出真实代码**在 vm 里跑）
  覆盖：插槽未声明时语言回调不注册/不抛错、注入后注册成功、语言切换重注册、插槽消失不炸、
  以及 10 种工具参数形状（含 `undefined`/`null`/无参对象）→ **ALL PASS**。
- 运行级：临时加 `console.warn('build-probe')` → **保存文件后 `dsh-client-hmr` 自动热加载**（DSH 桌面端没有浏览器式 F5，
  实测 probe 在按任何键之前 3 秒就出现了；手动 F5 不产生新的加载）→ 运行时日志出现 probe、**没有** `settings.section` 报错，
  说明新代码确实被加载。移除 probe 后再次自动热加载，日志零新增。
  验证后 `settings.section` 占位者仍为 `meow-memory / order 35 / active`（client Slots 检查）。
- ⚠踩坑记录：中途用 PowerShell `Get-Content -Raw` + `Set-Content` 改写 `lib/client.js`，PS 5.1 按 GBK 解码 UTF-8 源
  并写出带 BOM 的文件（141485 → 146362 字节），HMR 加载时报
  `client-modules: could not load "meow-memory": loaded without registering "meow-memory" via __ModuleLoader__.load`，
  整个插件在客户端失效。已用备份还原并用 `edit` 工具（UTF-8）重打补丁恢复正常。**插件 JS 一律不要用 PowerShell 管道改写。**
- 未做：没有真的点开折叠卡片做交互验证（需要盲点他人界面），该路径靠单测覆盖。

## 五、遗留 / 建议

1. **上游未修**：npm 上 0.32.0 的 `lib/client.js` 与本机 0.31.1 的 SHA256 完全相同
   （`1BCB063B…401720`），说明这两处还没进版本。发 0.32.1 时把上面的 TS 改动合进去。
2. **源码找回**：`lib/client.js.map` 的 `sourcesContent` 里有完整 TS 源码，已还原到
   `E:\DSH-WORKBENCH\ref\meow-memory-0.31.1-src\src\`（17 个文件），并按本修复同步改好
   `client-fold.ts / client.ts / settings-page.ts`。npm 包里不含 `build.mjs`，重建命令需另找原仓库。
3. **sourcemap 变旧**：`lib/client.js.map` 未重算，DevTools 行号会偏几行，不影响运行。
4. 引导期 `installation-v1.json.lock` 超时与 meow-memory 无关，是 **DSH 内核**问题（2026-10-27 确认）：
   残留锁会让 DSH 直接起不来，用户手工删掉 `E:\DSH\home\desktop\community\installation-v1.json.lock` 后恢复正常；
   锁文件不会自己过期。已另起 issue 稿（见 `meow-memory-issue-reports-20261027.md` 的 Issue 3）。
   （此前本小姐误判为"瞬时竞争、重启自愈"，已被用户纠正。）
