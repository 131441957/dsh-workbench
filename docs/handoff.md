# 工作台项目 · 新会话接手提示词

> 用法：把下面「=== 复制开始 ===」到「=== 复制结束 ===」之间的内容，原样发到新会话开头。

=== 复制开始 ===

接着做「DSH 工作台」项目。先做两件事：①`memory_project("workbench")` 拉项目全景；②`memory_search("工作台 顶栏 SSE 会话面板")` 补细节。记忆库是**跨工作区共享**的（用户定的方案 A），别乱改。

## 一句话背景
用户怕改坏主 harness，所以做了一套「工作台」：`E:\DSH-WORKBENCH` 里一份**独立整套** DSH 运行时（自己的 DSH_HOME、profile=bench、端口 59430，禁 agent），插件全装在这里；主 harness（`E:\SSS` + `E:\DSH\home`）**只读不动**，两边靠「接入层」通信。

## 铁律（违反过一次就别再犯）
1. **主 harness 一个字节都不许改**：`E:\SSS`、`E:\DSH\home`（尤其 `profiles\desktop\*`）只读。之前我为去掉弹窗手改过主 profile，被用户指出"第一次跨线"，已还原。
2. **桌面不盲操作**：曾对着以为是工作台的窗口按 Ctrl+R，实际刷了用户正在看的视频页。要操作先确认窗口标题/矩形；能用页面快照、HTTP、日志验证的，就别碰屏幕。
3. **改 profile 配置写进插件的包补丁**：`<home>\profiles\<p>\cordis.patch.yml` 会被应用在启动时**整体重写**，手加的行会消失；要持久化就写 `plugins\<pkg>\cordis.patch.yml`（`dsh.bundle.patch`）。
4. **改桥（主驾侧 host 代码）必须重启主程序**才生效——ESM 缓存不热更。改工作台侧（plugins/ui）只需 `wb.py restart`。
5. **改代码用编辑工具/写文件**，别用 PowerShell 拼字符串（`\n`、反引号、中文引号都会被吃掉）；改完 `node --check` / `py_compile` 复核。

## 现在的状态（已 20 项完成）
- **运行时**：`tools\wb.py`（Python 3.10 纯标准库）负责 install / start / stop / restart / suspend / resume / backup / restore / rollback / sync-app / api / compat / info / paths / caps / doctor；`tools\wb_gui.py` 是可视化安装器。
- **生命周期**：watchdog 盯主驾进程（主驾关→8 秒内关工作台）；supervisor 随登录自启（主驾开→拉起工作台）。
- **接入层**（装在主 profile，软依赖）：`plugins\dsh-workbench-bridge`，路由 `/wb-bridge/{status,plugins,sessions,session/page,session/prompt,events}`，token 在 `state\bridge-token.txt`（请求头 `x-wb-token`）；工具 `workbench_status / workbench_api / workbench_plugins / workbench_web_search`。
- **SSE 实时流**：桥 `/wb-bridge/events` 每 3 秒推 `{workbench:{reachable,latencyMs},sessions:{count,running,latest}}`；工作台代理 `/wb-sessions/events` 转发；面板用 EventSource 自动刷新。
- **工作台插件**：`dsh-wb-api-browser`（状态面板 key `wb-api`：宿主服务/前端槽位/profile 分层/主驾状态 **+ 独立「工作台插件」面板 key `wb-plugins`**，用 `h(Panel,{fixedTab:'plugins',hideTabs:true})` 复用同一份 Panel）、`dsh-wb-sessions`（Harness 会话：列表/历史/发送 + 标题）、`dsh-wb-ui`（webui 注入层）、`dsh-wb-web`（能力出口，重复能力，已标注）、`dsh-workbench-bridge`（主驾侧）。
- **UI 现状**：左栏已改**顶栏**（纯 CSS：`.OSewFq_frame` 强制 flex、隐藏 sidebar/rightbar/handle、centerCol 撑满；`body{padding-top:46px}`）。顶栏分组：左「Harness会话 / 插件」，右「状态 / 设置」。面板根节点带 `data-wb-panel`，`ui\workbench.js` 的 `maskUnknownMain()` 在面板就位前遮罩主区，避免「探索未至之境」闪一下（6 秒超时保护）。
- **会话面板**：290px 左栏；首部三行（标题/实时状态/过滤+排序）；按工作区分组、可折叠、组头加粗+胶囊计数+分隔线；行缩进 20px、运行中圆点发光；**标题来自桥透出的 `summary.projections.values.title`**（`/wb-sessions/list` 已带 `title`）。
- **设置页**：只留 语言 / 外观 / 字号大小；其余按标题文字隐藏（`pruneSettings()`，正则 `[\w-]+_(row|group|setting)`，别按 `[data-slot]` 判断——它包住整个区域）。
- **备份**：`wb.py backup --note "…"` → `backups\snapshot-<时间>.zip`（含 tools/plugins/seeds/docs/ui + config.json + home/profiles/bench + home/storages/*.json；**不收** credentials/app/state/logs）。现有 5 份快照全保留 + 运行时备份 `app-0.2.1-alpha.1-*`（1.69 GB，`rollback` 秒回）。

## 常用验证手段（别靠猜）
> git：本仓库**没有配全局身份**，直接 `git commit` 会报 `Author identity unknown`；用 `git -c user.name=meow -c user.email=meow@local commit -m "…"`，提交后 `git status --short` 必须为空。

```powershell
python E:\DSH-WORKBENCH\tools\wb.py status       # 端口/守护/版本
python E:\DSH-WORKBENCH\tools\wb.py info         # 单行 JSON（GUI 也用它）
python E:\DSH-WORKBENCH\tools\wb.py caps         # 工作台独有能力清单
curl  http://127.0.0.1:59430/wb-ui               # 注入层状态
curl  http://127.0.0.1:59430/wb-sessions/health  # 主驾端口/token
# 页面自报结构：POST /wb-ui/dom → state\dom-snapshot.json；控制台 __WB_UI__ / __wbSweep()
```

## 待办
1. **会话标题**：已完成，并已运行时复核（2026-10-26 22:48，`/wb-sessions/list` 三条标题均为中文正常：`检查 docs handoff.md 文件` / `DeepSeek harness 附属 Web 隔离方案` / `检查E盘可用插件`）。取值顺序=投影 `projections.values.title` → 日志兜底 → cwd 末段 → `#短号`。
2. **GitHub 远程仓**：用户明确「暂不上传」。
3. **能力注册表的“按名调用”通路**：等第一个**自研插件**出现再做（原则：只登记主驾没有的能力，`package.json` 的 `dsh.workbench.capabilities` 声明）。
4. **待用户拍板**：主 profile 里除 `meow-memory` 还有 `dsh-meow-panel` / `persona-preset` / 4 个第三方功能包——算不算“要隔离的插件”（A 宽松 / B 严格）。
5. 可选：细粒度会话事件推送（现在只有 tick 汇总）；`/wb-web` 与主驾 `web_search` 重复，可考虑下线。

## 用户偏好
中文、简短、要证据不要"应该可以"；改完要**运行时验证**；重要节点主动 `wb.py backup`（旧快照一律不删，备注写清楚）；不确定就报告，别闷头猜；别让他手动点窗口，能用脚本/接口就自己来。

=== 复制结束 ===
