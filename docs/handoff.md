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
- **接入层**（装在主 profile，软依赖）：`plugins\dsh-workbench-bridge`，路由 `/wb-bridge/{status,plugins,sessions,session/page,session/prompt,events}`，token 在 `state\bridge-token.txt`（请求头 `x-wb-token`）；工具 `workbench_status / workbench_api / workbench_plugins`（原 `workbench_web_search` 已于 2026-10-27 删除，见待办 6）。
- **SSE 实时流**：桥 `/wb-bridge/events` 每 3 秒推 `{workbench:{reachable,latencyMs},sessions:{count,running,latest}}`；工作台代理 `/wb-sessions/events` 转发；面板用 EventSource 自动刷新。
- **工作台插件**：`dsh-wb-api-browser`（状态面板 key `wb-api`：宿主服务/前端槽位/profile 分层/主驾状态 **+ 独立「工作台插件」面板 key `wb-plugins`**，用 `h(Panel,{fixedTab:'plugins',hideTabs:true})` 复用同一份 Panel）、`dsh-wb-sessions`（Harness 会话：列表/历史/发送 + 标题 + 工作区分组）、`dsh-wb-ui`（webui 注入层）、`dsh-workbench-bridge`（主驾侧接入层）。**`dsh-wb-web` 已于 2026-10-27 整体卸载**（它只是当初用来测工作台的样板能力出口，`/wb-web/search` 与主驾 `web_search` 重复）：profile 里的依赖/bundle 已删、node_modules 链接已剪、插件目录已从仓库移除（`/wb-web/*` 现在 404），源码仍在 git 历史与旧快照里，要恢复就 `git checkout` 旧版本 + `wb.py plugins add`。
- **UI 现状**：左栏已改**顶栏**（纯 CSS：`.OSewFq_frame` 强制 flex、隐藏 sidebar/rightbar/handle、centerCol 撑满；`body{padding-top:46px}`）。**顶栏不写死**（2026-10-27 改）：`ui\workbench.js` 动态扫描侧栏入口行（`[class*="_panelRow"]`）生成按钮，规则是 `LEFT_ORDER=['Harness会话','插件']`、`RIGHT_ORDER=['状态','设置']`、**名单里没有的入口自动排到左边末尾**——所以装/卸插件都不需要改工作台代码。兜底：`设置`不是面板行，名单里的名字扫不到行时按文字 `findButton` 补上。面板根节点带 `data-wb-panel`，`maskUnknownMain()` 在面板就位前遮罩主区，避免「探索未至之境」闪一下（6 秒超时保护）。
- **装插件的标准姿势**（2026-10-27 起）：`seeds\plugin-template\` 是现成模板，复制改名 → `wb.py plugins add <绝对路径>` → `wb.py restart`，顶栏自动出现新面板。**`plugins add` 必须传绝对路径**：profile 里写的是 `link:<路径>`，而 link 是相对 profile 目录解析的，传相对路径会装成一个不存在的目录（install 直接失败）。详见 `seeds\plugin-template\README.md`。
- **插件备注**（2026-10-27 新增）：顶栏「插件」面板里每个插件下面有一条备注，点一下就地编辑（`Ctrl+Enter` 保存 / `Esc` 取消 / 清空即删除），过滤框也能按备注内容搜。存 `state\plugin-notes.json`（UTF-8，先写 .tmp 再 rename），接口 `GET/POST /wb-api/notes`；该文件**已加进 `wb.py backup` 的 state 白名单**（`BACKUP_STATE_FILES`），别让它在快照里漏掉。
- **面板数据来源**（2026-10-27 修）：`/wb-api/live` 里**服务是实时枚举的**（走 `ctx.reflect.store` 的 Symbol 键，用属性描述符数方法，**绝不 `get` 服务对象**以免触发初始化），槽位是客户端概念、宿主拿不到，只能给 `api-live.json` 的快照并附 `slotsCollectedAt`；`/wb-api/build`（profile 分层）靠面板上的**「刷新基线」按钮**触发 `POST /wb-api/refresh` → 宿主 spawn `dsh --profile bench --dump-config` → 解析后重写 `api-build.json`。面板底部会把每条数据的来源和采集时间标出来，别再拿旧快照当实时数据。
- **第三方插件实验（2026-10-27，第一个真实案例 `dshmarket` 1.70.2）**：`wb.py plugins add dshmarket`（需要 `npm_config_registry=https://mirrors.cloud.tencent.com/npm/`）→ 装进 bench profile → restart → 能跑。它注册的是**设置里的一个分区**（`settings.section`，「插件市场」），不是主面板；点它自己的「侧栏显示」后，会多一条 `sidebar.panellist` 入口，**顶栏靠动态发现自动接上**（实测 5 个按钮：Harness会话 / 插件 / 插件市场 / 状态 / 设置）。踩到两个坑见下方验证段。
- **设置页导航列必须保留**（2026-10-27 修）：早先为了「只留语言/外观/字号」把 `.ZCYAFq_nav` 整列 `display:none`，结果**任何插件加的设置分区都点不到**。现在只隐藏 `.ZCYAFq_navTitle`/`.ZCYAFq_actions` 并压窄导航列，分区过滤交给 `KEEP_NAV` 白名单——**第三方插件加了设置分区，要把它的标题加进 `KEEP_NAV`**（已加「插件市场」）。
- **面板深链接**：地址栏 `#wb-panel=插件` 可直接打开指定面板（`ui\workbench.js` 的 `WANT_PANEL`）。必须用 **hash**——token 用完会重定向到 `/`，query 会被剥掉。
- **会话面板**：290px 左栏；首部三行（标题/实时状态/过滤+排序）；**按工作区分组**（默认排序=按工作区）：分组键是 `cwd`，组头显示工作区名——名字来自宿主新增接口 `/wb-sessions/workspaces`（只读主驾 `storages\workspace.json`，`default-workspace` 按原版规则显示成「默认工作区」），取不到才退回目录末段；可折叠、组头加粗+胶囊计数+分隔线；行缩进 20px、运行中圆点发光；**行标题来自桥透出的 `summary.projections.values.title`**（`/wb-sessions/list` 已带 `title`）。⚠️ 曾经分组键误用 `sessionLabel()`（优先标题），导致每条会话自成一组、组头全是标题——已修，回归测试 `tools\test-sessions-group.mjs`。
- **设置页**：只留 语言 / 外观 / 字号大小；其余按标题文字隐藏（`pruneSettings()`，正则 `[\w-]+_(row|group|setting)`，别按 `[data-slot]` 判断——它包住整个区域）。
- **备份**：`wb.py backup --note "…"` → `backups\snapshot-<时间>.zip`（含 tools/plugins/seeds/docs/ui + config.json + home/profiles/bench + home/storages/*.json；**不收** credentials/app/state/logs）。现有 5 份快照全保留 + 运行时备份 `app-0.2.1-alpha.1-*`（1.69 GB，`rollback` 秒回）。

## 把工作台挂到另一台机器 / 别人的 harness 上（2026-10-27）
```powershell
python tools\wb.py attach [--target-home <对方的 DSH_HOME>] [--target-profile desktop]          # 预览
python tools\wb.py attach --target-home <…> --apply                                              # 真正写
python tools\wb.py detach --target-home <…> --apply                                              # 撤掉
```
- **只碰目标 profile 的 `package.json`**（`dependencies` + `dsh.profile.bundles`）与 `node_modules` 里那条链接；**绝不碰安装目录（app.asar / E:\SSS）**。
- 装的是 `dsh-workbench-bridge` 一个包，且**强制软依赖**：`attach` 会先检查桥源码里有没有 `export const inject = []`，不是软依赖就**拒绝安装**（硬依赖会把目标 harness 打死）。
- 默认干跑（只打印计划）；`--apply` 才写，写前把目标清单备份到 `backups\attach-<时间>\` / `detach-<时间>\`。
- 目标 profile 没有 `dsh.profile.bundles` 时直接拒绝（不是 DSH profile）。
- 装/卸都要**重启目标 harness** 才生效（桥是 host 代码）。
- 演练办法（别拿真主 profile 试）：在 `state\` 下造一个假 home（`profiles\desktop\package.json` 带最小 bundles），用 `--target-home` 指过去走完整链路。

## 装一个带界面的插件（统一方法，2026-10-27 定）```powershell
python E:\DSH-WORKBENCH\tools\wb.py plugin-info   <包名>   # 只侦察：client 入口 / 注册槽位 / 设置分区 / peer
python E:\DSH-WORKBENCH\tools\wb.py install-plugin <包名|目录> [--keep-nav 标题] [--no-restart]
```
`install-plugin` 一条命令做完五件事：①装进 bench profile（pnpm，走 `home\profiles\bench\.npmrc` 里的镜像）②按 `package.json` 的 `exports["./client"]` 找客户端入口、解析 `slots.inject/register`（含 `const SLOT='…'` 常量写法）认出它会露在哪 ③把设置分区标题写进 `state\ui-config.json` 的 `keepNav`（**裁剪白名单已从 `ui\workbench.js` 搬到这个文件，读 `/wb-ui/config`**，所以装插件再也不用改代码）④安全重启（先 stop、等端口真的释放、再 start，避开 EADDRINUSE 假故障）⑤验证：端口 / bundle+linked / 页面模块表里有没有 `<包名>/client.js` / **本次启动**（按日志偏移量算）有没有 EADDRINUSE 或 startup failed。

两条坑要记住：
- **市集卡片上的短名 ≠ npm 包名**。`dsh-message-ops` 的真名是 `@240xu/dsh-message-ops`；权威数据在 `https://awesome-dsh-plugin.com/plugins.json`（含 `npm`、`install`、`capabilities` 字段）。
- **很多“可视化插件”注册的是 `conversation.*` / `chat.*` / `composer.*` 槽位**，而工作台没有会话界面（不接 agent）——装了功能在、界面看不见。`install-plugin` 会对这种情况明确告警，别以为装失败。


## 常用验证手段（别靠猜）

> git：本仓库**没有配全局身份**，直接 `git commit` 会报 `Author identity unknown`；用 `git -c user.name=meow -c user.email=meow@local commit -m "…"`，提交后 `git status --short` 必须为空。
> 重启会换 token：`wb.py restart` 之后，已经开着的页面 cookie 失效（主区全白）。**必须**把页面导航到 `wb.py url` 打出的新地址（`Ctrl+L` 输入后可能要按两次 Enter，第一次会被地址栏下拉建议吃掉）。
> 动浏览器之前**每次都要重新确认标签**：标题里的「和另外 N 个页面」就是标签数，活动标签不一定还是上次那个。2026-10-27 我沿用昨晚「只有一个标签」的结论直接导航，把用户正开着的 dsh-market 页面顶掉了（已用 `Alt+←` 恢复）。正确做法：先 `Get-Process msedge → MainWindowTitle` + 截图看清标签，再决定按键。
> `wb.py restart` 有**抢端口风险**：真凶是 **supervisor 看到端口空出来就抢先起一个实例**，和我们这次的启动抢端口 → 新实例 `listen EADDRINUSE … 127.0.0.1:59430` → webserver 挂 → `startup failed: N required plugins did not activate`（12 个 pending）。**维护型重启一律走 `safe_restart`（suspend → 等端口释放 → start → resume）**；手工遇到时先 `wb.py suspend`，起来后再 `wb.py resume`。看到 startup failed 先别怪插件：确认 59430 只有一个 owner + 看 `home\logs\startup-*.log`。

```powershell
python E:\DSH-WORKBENCH\tools\wb.py status       # 端口/守护/版本
python E:\DSH-WORKBENCH\tools\wb.py info         # 单行 JSON（GUI 也用它）
python E:\DSH-WORKBENCH\tools\wb.py caps         # 工作台独有能力清单
python E:\DSH-WORKBENCH\tools\wb.py url          # 带 token 的当前地址（重启后必用）
curl  http://127.0.0.1:59430/wb-ui               # 注入层状态
curl  http://127.0.0.1:59430/wb-sessions/health  # 主驾端口/token
curl  http://127.0.0.1:59430/wb-sessions/workspaces  # 工作区注册表（分组显示名）
# 页面自报结构：POST /wb-ui/dom → state\dom-snapshot.json；控制台 __WB_UI__ / __wbSweep()
# 开机自诊断：每次加载页面 4.6 秒后自动写 state\boot-diag.json（按钮表 / hasPanel / clickLog / JS 报错 / console.error / **discovered 侧栏发现 / topbarTabs 顶栏按钮**）
node E:\DSH-WORKBENCH\tools\test-sessions-group.mjs   # 分组回归（工作区 vs 标题）
node E:\DSH-WORKBENCH\tools\test-plugin-notes.mjs     # 插件备注的行数据形状（note 字段/筛选/其它标签不受影响）
node E:\DSH-WORKBENCH\tools\test-capabilities.mjs     # 能力声明校验（route 在本插件 PREFIX 下、名字唯一、method 合法）
python E:\DSH-WORKBENCH\tools\wb.py plugins list        # 工作台插件（bundle/linked/spec）
python E:\DSH-WORKBENCH\tools\wb.py plugins remove <名> # 卸载：删依赖+bundle → pnpm install
```

## 待办
1. **会话标题**：已完成，并已运行时复核（2026-10-26 22:48，`/wb-sessions/list` 三条标题均为中文正常：`检查 docs handoff.md 文件` / `DeepSeek harness 附属 Web 隔离方案` / `检查E盘可用插件`）。取值顺序=投影 `projections.values.title` → 日志兜底 → cwd 末段 → `#短号`。
2. **GitHub 远程仓**：用户明确「暂不上传」。
3. **能力「按名调用」通路：已完成（2026-10-27）**。链路：插件在 `package.json` 的 `dsh.workbench.capabilities` 声明 `{name, description, method, route, query?, body?}` → 工作台 `GET /wb-api/capabilities` 汇总（api-browser 宿主扫描 `plugins\*\package.json`）→ 主驾桥 `GET /wb-bridge/capabilities`（20 秒缓存，`?fresh=1` 强刷）与 `POST /wb-bridge/call`（带 `x-wb-token`，body `{name, params}`）→ 主驾工具 `workbench_call`（`name:"capabilities"` 即可列出全部）。校验脚本 `tools\test-capabilities.mjs`：route 必须落在本插件 `PREFIX` 之下、名字不可重复、method 只能 GET/POST。现有 8 条：`sessions_list / sessions_page / sessions_send / workspaces / plugins / notes / note_set / capabilities`。⚠️ 桥属主驾侧 host 代码，**改完要重启主程序才生效**。**已重启并验证（2026-10-27）**：`workbench_call` 能列出 8 条能力、按名调 GET（`sessions_list`）、带 query（`sessions_page` 传 id/max）、POST（`note_set` 写入并回显）；传错名字返回 `可用能力：…` 列表；直连 `POST /wb-bridge/call` 带 `x-wb-token` 返回 200，不带返回 401。
4. **已关闭（2026-10-26 用户拍板）**：主 profile 现有插件（除 `meow-memory` 外还有 `dsh-meow-panel` / `persona-preset` / 4 个第三方功能包）**一律不动、不隔离、不搬**。用户原话「不用，现在的插件都不用动，因为我暂时不会去修改它」。别再拿 A/B 方案来问。
5. **已完成（2026-10-27）**：`/wb-web` 已随 `dsh-wb-web` 插件卸载（用户原话「那就给他撤掉，而且这个插件是用来测试工作台的，完全卸载掉也可以」）。顺带给 `wb.py plugins` 补上了 `remove` 动作（原来文档写了但没有实现）。剩可选项：细粒度会话事件推送（现在只有 tick 汇总）。
6. **已完成（2026-10-27，用户同意后动的主 profile）**：主驾桥里的 `workbench_web_search` 工具已删除（连同指向 `/wb-web/search` 的 `wbSearch()`、schema、render、注册行与日志文案）；桥里现在只剩 `workbench_status / workbench_api / workbench_plugins` 三个工具。改动前备份在 `backups\pre-bridge-nowebsearch-20261027-1112\`（含 index.js / package.json / 主 profile package.json）。⚠️ **桥是主驾侧 host 代码，必须重启主程序才生效**；重启前主驾进程里仍是旧代码。

## 用户偏好
中文、简短、要证据不要"应该可以"；改完要**运行时验证**；重要节点主动 `wb.py backup`（旧快照一律不删，备注写清楚）；不确定就报告，别闷头猜；别让他手动点窗口，能用脚本/接口就自己来。

=== 复制结束 ===
