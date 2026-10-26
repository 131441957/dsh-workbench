# 工作台（Workbench）工具盘点 v0.1

> 本文件对应你说的「先确定需要什么工具，有没有缺少工具，可以先构建工具」。

## 一、已定决策（你 2026-10-26 的答复）

| 问题 | 你的答复 | 落地含义 |
|---|---|---|
| Q1 安装形态 | 100G 不用省空间，本地 PC | 磁盘不是约束（E 盘剩 96GB），用**独立整套**，不共用 `E:\SSS` |
| Q2 webui 改造深度 | 主 harness 不用大改，主要显示有没有接入工作台 | 主驾**只加一个接入状态显示**；壳不动 |
| Q3 旧副驾 | A（废弃重建），**要的不是副本 harness** | 旧 `E:\DSH-PLUGIN` / 59420 淘汰；工作台不是"第二个聊天 harness"，是插件宿主 |
| Q4 记忆归属 | 记忆最重要，放主驾是为了注入对话；工作台只读 | meow-memory 只在主 profile；工作台只读访问记忆库 |

你另外两条建议：
1. **先确定需要什么工具、缺什么，可以先构建工具** ← 本文件就是这件事
2. **构建不要用 PowerShell，用 Python / Java 扩展性更强**

## 二、语言分工（这里有个硬约束，先讲清楚）

| 层 | 能用的语言 | 原因 |
|---|---|---|
| 外围工具（启停/备份/监控/脚手架） | **Python 3.10**（已就绪，只用标准库，不装 pip 包） | 你的要求；跨平台、好扩展 |
| DSH 插件本体 | **只能 JavaScript** | Cordis 加载的是 `package.json` + `cordis.patch.yml` + `client.js/index.js`，运行时就是 Node，Python 无法"挂进 harness" |
| Java | 当前**未安装** | 如果确定要有 Java 组件，先装 JDK 21，再告诉我放哪一层 |

结论：**工具用 Python，插件用 JS**。这不是偏好吗，是 DSH 的加载器只认 JS。

## 三、工具清单

| # | 工具 | 干什么 | 语言 | 状态 |
|---|---|---|---|---|
| 1 | `wb.py doctor` | 运行时/依赖/接口/目录自检 | Python | ✅ 已完成并跑通 |
| 2 | `wb.py status` | 主驾 + 工作台状态（端口/进程/home/记忆条数） | Python | ✅ 已完成并跑通 |
| 3 | `wb.py watch` | 采集主 harness 状态快照 → `state/main-status.json` | Python | ✅ 已完成并跑通 |
| 4 | `wb.py start/stop/restart` + `sync-app` | 工作台启停；**无窗口**；**看门狗绑主驾生命周期** | Python | ✅ 已完成并实测（看门狗用假主驾验证过会关掉工作台） |
| 5 | `wb.py plugins` | 列插件 / 安装（link）/ 生成 profile patch / 触发 reload | Python 调 bundled pnpm.mjs | ⬜ 待造 |
| 6 | `wb.py api` | 导出 Service / Event / Slots / Theme 清单，做**接口基线** | Python | ⬜ 待造（优先级 2） |
| 7 | `wb.py backup` | 独立快照（git 提交 + manifest + 回读校验） | Python + git | ⬜ 待造 |
| 8 | `wb.py scaffold` | 新建插件模板（package.json / patch / client.js / index.js） | Python | ⬜ 待造 |
| 9 | 主驾「工作台接入」状态插件 | 主界面显示工作台在线/离线（主驾**唯一**改动） | JS | ⬜ 待造 |
| 10 | 工作台 UI 外壳 | 注入式改皮/布局（`webServer.tapIndex`），不碰安装目录 | JS | ⬜ 待造 |
| 11 | 无窗口快捷方式 | 桌面「DSH 工作台」→ `pythonw wb.py open`，不闪窗、自动带最新 token | .lnk + pythonw | ✅ 已完成 |

## 四、环境现状（`wb.py doctor` 实测）

```
python      3.10.11   C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe
node        24.22.0   E:\nodejs\node.exe
pnpm.mjs    ok        E:\DSH\home\dsh-runtimes\...\pnpm\bin\pnpm.mjs（不在 PATH，工具里直接用绝对路径）
git         ok        C:\Program Files\Git\cmd\git.exe
java        缺失
主 GUI 端口  每次重启都变（现 56853），wb.py 自动识别
记忆库      可只读访问：user=7 / project=29 / fact=227 / lesson=34 / topic=39 / rules=3
```

## 五、下一步顺序（等你点头）

1. **start/stop + 看门狗**：先把工作台实例能起能停，且主 harness 一关它自己退
2. **接口基线**（`wb.py api`）：把你要求的"先确认接口"落成一份可查的清单
3. **插件安装/热重载**（`wb.py plugins`）
4. **主驾接入状态显示**（主驾唯一改动）
5. **UI 外壳注入**（webui 修改在工作台里做）
6. **备份 + 私有 GitHub 仓**

## 六、待你确认的一句话

「不是副本 harness」我按这个理解落地：**独立一整套安装 + 独立 home/配置/插件/端口/升级，且不提供聊天功能，只做插件宿主**（不是把主 harness 克隆一份来用）。
如果你要的是更彻底的东西（比如完全不用 DSH、用 Python 自建宿主），代价是现有 `meow-*` 插件无法复用、需按新规范重写——那样的话告诉我，我改方案。

## 生命周期与看门狗（2026-10-26 实测）

- 看门狗用 **WMI Win32_Process.Create 启动**（父进程 `WmiPrvSE.exe`），因此它**不会随主程序退出被带走**——否则没人去关 59430。
- 轮询：8 秒一次；端口探测用 `socket.create_connection`，进程存活用 `ctypes OpenProcess + GetExitCodeProcess`（**不 spawn 任何子进程**，桌面不会闪窗）。
- 实测（用 3 秒就死的假主驾）：
  ```
  watchdog start, main pids=[9724]
  main harness gone → stopping workbench
  workbench not listening any more → watchdog exit
  59430 已释放
  ```
- 行为约定：主程序（含托盘“完全退出”）关闭 → 8 秒内工作台关闭；主程序重新打开后**不会**自动拉起工作台（双击桌面「DSH 工作台」即可）。

## 自动伴随（supervisor）与快捷方式（2026-10-26）

- **桌面「DSH 工作台」** = `pythonw wb.py page` → **只打开页面**，不启动任何服务。
- **开机自启「DSH 工作台（自动伴随）」**（启动文件夹）= `pythonw wb.py supervise`：
  - 每 8 秒检查：主程序在 + 59430 没起 → 自动拉起；主程序没了 → 收掉工作台
  - 实测：`workbench missing → starting`；手动 stop 后 8 秒内自动恢复
- **临时要停**：`wb.py suspend`（先停守护再停服务，否则会被拉回来）；恢复：`wb.py resume`
- 坑：`wb.py stop` 曾把 pids.json 整个清空，导致 supervisor 记录丢失；现在只清 serve/watchdog，且 `read_pids()` 兼容 BOM（PowerShell 写 UTF8 会带 BOM，`json.loads` 会直接失败）。

## 自主安装（2026-10-26 实测）

- **双击桌面「DSH 工作台」就是安装器**：没装运行时 → 自动复制安装（约 3 秒 / 10009 文件）→ 铺 profile 与种子 → 装插件依赖 → 重建快捷方式 → 起工作台与守护 → 打开页面。
- **主驾升级后也走同一条路**：检测到「主驾版本 ≠ 工作台版本」→ 自动 `sync-app --force`（旧运行时改名备份到 `backups\`）→ 再启动。
- 命令行等价：`wb.py install`（幂等，可反复跑）、`wb.py install --force`（强制重装）、`wb.py rollback`（回滚运行时）。
- 实测：把 `app\` 整个挪走后跑 install → 3 秒铺回 1691MB → 页面 200、`/wb-web/health` 正常。

## 可视化安装器（2026-10-26）

- 桌面「**DSH 工作台 安装器**」= `pythonw tools\wb_gui.py`（tkinter，只用标准库）。
- 按钮：安装/修复、同步运行时(重装，旧版备份可回滚)、回滚运行时、启动、停止、打开页面、暂停/恢复自动伴随、刷新状态；下方是实时日志。
- 桌面「**DSH 工作台**」= `wb.py page`：**只开页面**，不再自动复制 1.7GB、不再自动升级；缺运行时只会提示去点安装器。
- 自检：`python tools\wb_gui.py --selftest`（建窗口 0.4s 自关，验证不崩）。

## 路径自动识别（2026-10-26）

- `wb.py` 不再写死 `E:\SSS` / `E:\DSH\home`。识别顺序：
  - **安装目录**：运行中的主程序进程 → 桌面/开始菜单快捷方式 → 注册表卸载项 → 常见位置（E:\SSS、E:\SOS、Program Files…）
  - **数据目录**：`DSH_HOME` 环境变量 → 安装目录旁 `DSH\home` → 安装目录内 `home` → `%USERPROFILE%\.dsh` → `E:\DSH\home`
- 识别结果写入 `E:\DSH-WORKBENCH\config.json`（带来源字段），之后直接复用；缓存路径失效会自动重新探测。
- 手动覆盖 / 重新探测：`wb.py paths --redetect`、`wb.py paths --install <路径> --home <路径>`。
- 安装器界面顶栏显示“主驾安装：…（来源）”和“数据：…（来源）”，并有「重新探测路径」按钮。

## 边界：绝不重装主 harness（2026-10-26）

- 主 harness **只升级、不重装**：升级走 `E:\newwork\update-dsh.ps1`（备份 home/data/plugins/exports → 安装 → 核对 → 可 `-RestoreFrom` 回滚）。
- 工作台的「同步运行时」**只是把主驾当前安装复制到 `E:\DSH-WORKBENCH\app`**，旧的那份改名进 `backups\`，可用「回滚运行时」秒级切回。**不碰 `E:\SSS`，不重装任何东西。**
- 界面已把按钮改名为「同步运行时（复制主驾安装）」，并在执行前弹确认框写明「不会重装、不会修改主驾」。
- 若将来 harness 本体真坏了：正确顺序是「先备份 home → 装同版本到新目录 → 用 DSH_HOME 指回原 home → 验证」，而不是覆盖重装。

## page 的行为（2026-10-26 修复多开 bug 后）

- **主驾没开** → 立刻打开一张本地说明页 `ui\landing.html`，写明“工作台跟着主程序开关”，不再无声干等。
- **单实例锁** `state\page.lock`：连点时只有一个请求在处理，其余直接忽略。
- **冷却 5 秒** `state\last-open.txt`：5 秒内重复打开会被忽略，杜绝一次弹出多个标签页。
- **主驾开着但工作台未起** → 拉起守护并最多等 20 秒（守护通常 8 秒内拉起），起来就打开。
- 历史 bug：以前 `page` 会阻塞等 45 秒且无单实例保护，连点几次后主驾一启动就会同时弹出多个页面。

## 备份与还原（2026-10-26，改 webui 前的保险）

- `wb.py backup --note "说明"` → `backups\snapshot-<时间>.zip`：收 **tools（含安装器 wb_gui.py）、plugins、seeds、docs、ui、config.json、.gitignore、home\profiles\bench 的清单**；不含 app/（1.7GB 运行时，可 sync-app 重建）、home 数据、logs/state/backups、node_modules、__pycache__。
- 每个文件都记 sha256 进 `MANIFEST.json`，写完**回读校验**；`restore` 前也先校验快照自身完整性。
- `wb.py backups` 列出快照；`wb.py restore --from <zip|latest>` 还原：先停工作台 → 把当前状态另存 `backups\before-restore-<时间>` → 解包 → 复原 profile → 跑 install。
- **坑**：快照比修改旧时，restore 会把**代码也回滚**（本会话就被回滚掉了刚加的排除规则）。所以修完代码要重做基线，旧快照该删就删。
- 运行时另有一份完整备份：`backups\app-0.2.1-alpha.1-*`（10009 文件 / 1691MB），`wb.py rollback` 可秒回。

## 会话视图（2026-10-26 新增，需求：主驾会话在工作台里看 + 能发消息）

- **数据永远在主驾**：工作台不落盘、不复制会话。
- 链路：工作台面板 → `/wb-sessions/*`（工作台代理）→ 主驾桥 `/wb-bridge/session*` → `sessionController` 的 `list / page / prompt`。
- 安全：会话路由必须带 `x-wb-token`，token 由主驾桥启动时生成并写到 `state\bridge-token.txt`，工作台读取后带上；普通网页/其它进程无法伪造。
- 面板：左侧会话列表（运行中标记、10 秒自动刷新）、右侧历史（最近 50 条文本消息）、底部发送（排队 queue / 插入 steer）。
- 注意：发送 = 往主驾那个会话投递一条用户消息，**会让它开始运行**（会消耗 token）。
- 依赖：`wb.py` 的 supervisor 现在每轮都刷新 `state\main-status.json`，工作台靠它拿到主驾端口。

## webui 注入（tapIndex，2026-10-26 完成）

- 插件 `dsh-wb-ui`（只挂工作台）用 `webServer.tapIndex(html => html)` 纯字符串改写 index：
  把 `ui\workbench.css` 注入到 `</head>` 前（`<style id="wb-ui-css">`），`ui\workbench.js` 注入到 `</body>` 前（`<script id="wb-ui-js">`）。
- **每次请求都重新读文件** → 改 css/js 后刷新页面即生效，不用重启、不用重建。
- **不碰安装目录**：删掉/改名 ui 文件 → 下次请求就没有注入（已实测）；停用插件同样。
- 状态接口：`GET /wb-ui` 返回 uiDir、两个文件的大小与 mtime、以及 index 渲染次数。
- 实测：注入出现在 head；改 css 后页面立刻含新内容；把 css 改名 `.off` 后页面立即无注入；改回即恢复；测试探针已清除。
- 能改：颜色/字体/圆角/间距、隐藏元素、浮层角标、全局脚本。
  不能改：新增页面、替换整体布局（那要客户端插件）。

## 快照清单与还原提醒（2026-10-26）

- 每次 `wb.py backup` 会重写 `backups\README.md`：列出所有快照（名字/时间/文件数/备注，备注里的 `|` 已转义）；`wb.py backups` 也会刷新它。
- `wb.py restore --from <非最新快照>` 会先警告：**还原会把该快照之后的改动一起回滚**（这是真实风险，不是吓人）。用户可以选择保留旧快照作对照，但要知道这一点。

## 去掉「预览版说明」弹窗（2026-10-26）

- 机制（从其自身文档挖出）：客户端把内置常量 `WELCOME_NOTICE_VERSION = "2026-09-28.1"` 与 settings 里的 `ui-settings-general.welcomeNoticeVersion` 做**严格相等**比较，相等才不弹；只有点「继续」才写入。
- 做法：在 profile 补丁层直接写这个值（等价于点过一次「继续」）：
  ```yaml
  - id: ui-settings-general
    name: "@deepseek-ai/dsh-client-ui-settings-general"
    config:
      welcomeNoticeVersion: "2026-09-28.1"
  ```
- 只写入工作台 `home\profiles\bench\cordis.patch.yml`（立即生效，刷新即可）。**主驾 profile 不写入**：曾越线改过一次，已按备份 `E:\newwork\backup\pre-ui-notice-20261026-210347` 完整还原（哈希一致、无残留）。主驾要去掉弹窗，由用户自己在界面点一次「继续」，或明确授权后再改。
- 双保险：`ui\workbench.js` 里加了自动点「继续」的兜底（MutationObserver 未用，改为定时尝试点击对话框里的「继续」按钮，最多 40 次 × 0.5s），版本号将来变了也能自动关掉。
- 想让它重新出现：把版本值改成别的字符串即可。

## 关掉工作台里用不到的原版界面（2026-10-26）

- 目标：左侧栏的「插件」「自动化任务」「工作区」三项原版入口去掉（由工作台自己的面板替代）。
- 对应客户端插件行：`ui-plugin-manager`（插件）、`ui-schedule`（自动化任务）、`ui-workspace`（工作区）。
- **关键坑**：直接改用户的 `home\profiles\bench\cordis.patch.yml` 加 `disabled: true` **会被应用在启动/设置写回时抹掉**（本会话试过一次，重启后行就没了）。正确做法＝写进**工作台自己的插件包补丁** `plugins\dsh-wb-ui\cordis.patch.yml`，由组装阶段应用，应用不会重写它。
- 实测：`dump-config` 三行都带 `disabled: true`；页面模块表里 `client-ui-schedule` 已消失；`plugin-manager` / `workspace` 的模块名仍在（被别的模块当依赖引用），但对应插件行是 disabled，侧栏入口不再注册。
- 顺带：`welcomeNoticeVersion` 也移进了包补丁（用户补丁层留不住 volatile 字段）。

## 精简左侧栏（2026-10-26，含一次把工作台搞挂的教训）

- **坑**：`ui-workspace` 不只是「工作区」页面，它还**提供服务 `uiWorkspace`**。禁用它会连带 `ui-sidebar` / `ui-conversation` / `ui-chat` / `ui-subagent` 等 **11 个插件 pending**，浏览器直接报 `Failed to load plugins / web boot: 11 entries did not activate`。
- 结论：**只禁用“纯页面、不提供服务”的行**。目前工作台禁用了 `ui-plugin-manager`（插件页）与 `ui-schedule`（自动化任务），实测无 pending。
- 「工作区」改为**按文字隐藏**（`ui\workbench.js` 的 HIDE_TEXTS = 插件/自动化任务/工作区/默认工作区，配合 MutationObserver 节流重扫），不动插件依赖，改完刷新即生效、删掉脚本即恢复。
- 排查口诀：页面报 `pending (waiting for service: xxx)` 时，去看是哪个被禁用的行提供了该服务——先恢复它，再改用隐藏。
