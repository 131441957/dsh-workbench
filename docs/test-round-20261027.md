# 完整测试轮（2026-10-27 13:36–14:10）

> 目标：在“功能面清空”之后，做一轮覆盖**离线单测 → 接口 → 桥 → 分发 → 破坏性演练 → 跨版本**的全量验收。
> 环境：主工作台 `E:\DSH-WORKBENCH`（alpha.1，端口 59430）、rc.3 测试床 `E:\WB-RC3`（rc.3，端口 59480）、主驾 `E:\SSS`。

## 一、结果总表

| # | 项目 | 用例数 | 结果 | 证据 |
|---|---|---|---|---|
| 1 | 离线单测 | 4 | ✅ 全过 | `test-markdown` / `test-sessions-group` / `test-plugin-notes` / `test-capabilities` 均 `pass:true` |
| 2 | CLI 冒烟 | 8 | ✅ | `status` / `caps` / `compat` / `plugin-update` / `plugin-search` / `backups --json`（29 份快照） |
| 3 | 接口 + 页面（主工作台） | 17 | ✅ 17/17 | 含 `/wb-ui`、`/wb-api/*` 6 个、`/wb-sessions/*` 2 个、页面标题与注入 |
| 4 | 主驾桥 | 4 | ✅ | status 可达、capabilities 10 条、`call(plugins)` 返回 4 个；`call`/`sessions` 无 token 均 401 |
| 5 | 接口 + 页面（rc.3 床） | 11 | ✅ 11/11 | 同一套用例在 rc.3 上跑通 |
| 6 | 分发验收 | 5 | ✅ | `prepublish` 退出码 0；`pack` 47 文件 / **0 绝对路径**；无 dshmarket；内部文档 0 泄漏；`config.template.json` 在 |
| 7 | 安装器 GUI | 1 | ✅ | `wb_gui.py --selftest` → `gui selftest ok`，退出码 0 |
| 8 | 备份→破坏→还原 | 3 | ✅ | css 哈希回到基线 `B49C71…`；删掉的插件文件恢复；快照里的新代码没被回滚 |
| 9 | 安全模式 | 2 | ✅ | `start-safe` 禁掉 `dsh-market`（模块表无、我们三个在）→ `restart-safe` 后 market 回归 |
| 10 | 零代码插件闭环（rc.3 床） | 4 | ✅ | 装 → `discovered: 插件/状态/Harness会话/**模板面板**/更多`；卸 → 该入口消失、无残留 |

## 二、本轮抓到并修掉的问题

| # | 问题 | 影响 | 修法 |
|---|---|---|---|
| 1 | `main_harness_ports()` 按**进程名**收集端口 | 主驾端口列表里混进了工作台自己的 59480 和无关的 3081；桥测试/看门狗可能盯错端口 | 改为按**可执行路径**剔除 `\dsh-workbench\app\` 与 `\wb-` 前缀的进程 |
| 2 | `tools/test-http.py` 默认根写死 `E:\DSH-WORKBENCH` | 一进分发包就变成 absolutePathHits=1（客户机上还不可用） | 默认改为 `Path(__file__).parent.parent`，环境变量可覆盖 |
| 3 | `dsh-wb-ui` / `dsh-wb-sessions` / `dsh-workbench-bridge` 三处 `WB_ROOT` 写死主工作台 | rc.3 床上 `/wb-ui` 回报的 `uiDir` 是**主套的 ui**，等于床在服务主套界面（同机多实例串味） | 统一改成 `fileURLToPath(new URL('.', import.meta.url))` 推导根目录 |
| 4 | `install-plugin` 只验“模块表里有 client.js”，不验**客户端是否真的激活** | 复制模板只改 package.json 时，浏览器整页 `Failed to load plugins`（本轮实测白页） | 新增静态闸门：`client.js` 里 `__ModuleLoader__.load({ id })` 必须等于包名，否则装前直接拒绝并给出改法 |
| 5 | 模板文档没说清这个 id | 同 #4，容易踩 | `seeds\plugin-template\README.md` + `client.js` 注释写明；并补上“根目录别写死”的写法 |

## 三、测试脚本自身踩的坑（先怀疑测试）

1. 会话列表键是 `items`，我按 `sessions` 取 → 误报 0 条
2. 主驾端口在 `main-status.json` 的 `mainHarness.ports`，我按顶层 `ports` 取 → 找不到
3. `/wb-bridge/status` 与 `/capabilities` 是**设计上公开**的只读接口；鉴权只在 `call` / `sessions` / `page` 上。我最初断言 status 也要 401 → 误报
4. `/wb-bridge/call` 只收 POST，用 GET 测会得到 405 而不是 401

## 四、没覆盖到的 / 受限的

- **无头浏览器 DOM 校验不可用**：`msedge --headless --dump-dom` 在这套 SPA 上会挂住（页面维持长连接，load 事件不结束）。改用“独立 profile 的有头窗口 + 页面自报 `boot-diag.json`”，验证完按自己启动的 pid 关闭，不碰用户窗口。
- 真实客户机（另一台机器）仍未验：本机所有版本都是“同机多实例”。跨机器验证需要另一个人/机器。
- `dshmarket` 仍是测试插件，不进分发包；本轮未再测它的升级（上一轮已验 1.70.2 → 1.71.1）。

## 五、怎么复跑

```powershell
# 离线单测
foreach ($t in 'markdown','sessions-group','plugin-notes','capabilities') { node tools\test-$t.mjs }

# 接口（主工作台，含桥）
python tools\test-http.py --bridge

# 接口（rc.3 床，无桥）
$env:DSH_WORKBENCH_ROOT='E:\WB-RC3'; python E:\WB-RC3\tools\test-http.py

# 分发
python tools\wb.py prepublish ; python tools\wb.py pack --force

# 安装器
python tools\wb_gui.py --selftest
```
