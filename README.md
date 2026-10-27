# DSH 工作台（dsh-workbench）

一套**独立于主 harness** 的插件宿主：自己的 DSH 运行时副本、自己的 profile、自己的端口，
插件与界面改造全在这里做，主 harness 只保留一个**软依赖**接入层，可随时摘掉。

> 为什么做这个：改主 harness 的 webui 曾把它弄到无法修复。工作台把这类风险关进笼子——
> 工作台炸了重装工作台，主驾不受影响。

## 组成

| 目录 | 内容 |
|---|---|
| `tools/wb.py` | 全部运维命令：install / start / stop / restart-safe / backup / restore / rollback / plugins / install-plugin / uninstall-plugin / fix-ui / attach / detach / pack / caps / compat / doctor |
| `tools/wb_gui.py` | 可视化安装器（装/修/启停/备份/还原/回滚，含构建信息行） |
| `plugins/dsh-wb-ui` | 界面注入层：用 `webServer.tapIndex` 改写首页，注入 `ui/` 的 CSS/JS（与换 harness 的 webui 同一套机制） |
| `plugins/dsh-wb-sessions` | 主驾会话查看器（列表 / 历史 / 发送 / 按工作区分组 / SSE 实时状态） |
| `plugins/dsh-wb-api-browser` | 状态面板：宿主服务（实时枚举）/ 前端槽位 / profile 分层 / 主驾状态 + 插件台账与能力清单 |
| `plugins/dsh-workbench-bridge` | 主驾侧接入层（**软依赖**）：`/wb-bridge/*` 路由 + `workbench_status/api/plugins/call` 工具 |
| `ui/` | 工作台界面改造的全部内容（`workbench.css` 带逐段注释，`workbench.js` 是顶栏/遮罩/设置裁剪）｜**改界面先读 [docs/webui-guide.md](docs/webui-guide.md)** |
| `seeds/` | 新建 profile 用的模板（`${WB_ROOT}` 占位，安装时渲染） |
| `docs/` | 交接、接口基线、升级策略、插件问题台账 |

## 快速开始

**最省事：分发包里双击 `install.cmd`**（会自动做体检 → 装运行时 → 建 profile → 装接入层 → 打印入口）。

命令行等价物：

```powershell
python tools\wb.py setup            # = preflight + install + attach（幂等，重复跑安全）
python tools\wb.py page             # 打开页面（带 token）
```

想看清每一步就分步跑：

```powershell
python tools\wb.py install          # 复制一份主驾运行时到 app\，准备 bench profile
python tools\wb.py attach           # 预览：把桥装进主驾 profile（确认后加 --apply）
python tools\wb.py start            # 启动工作台
python tools\wb.py page             # 打开页面（带 token）
```

装插件：

```powershell
python tools\wb.py plugin-info   <包名>     # 侦察：会露在哪、注册哪些槽位
python tools\wb.py install-plugin <包名>    # 装 + 登记界面白名单 + 安全重启 + 验证（失败自动回滚）
python tools\wb.py uninstall-plugin <包名>  # 卸干净（profile / node_modules / 白名单 / 台账）
```

## 设计要点

- **主 harness 只读**：不改 `app.asar`、不改安装目录、不碰主 profile 里除接入层以外的东西。
- **接入层必须软依赖**：`export const inject = []` + `ctx.get()` 重试；硬依赖会把主驾打死，`attach` 会强制检查这一条。
- **装插件不改代码**：顶栏动态发现面板（扫侧栏 `*_panelRow`），新插件自动出现。
- **能力按名调用**：插件在 `package.json` 的 `dsh.workbench.capabilities` 声明，主驾用 `workbench_call` 调。
- **端口/路径可移植**：端口 `config.json` 可配、被占自动避让；根目录从脚本位置推导；种子用占位符渲染。
- **可分发包**：`wb.py pack` → `dist/DSH-Workbench-<版本>/`，排除运行时/状态/内部文档与测试插件，`MANIFEST.absolutePathHits` 必须为 0。

## 不进仓库的东西

`app/`（运行时副本，~1.7 GB）、`home/`、`state/`、`logs/`、`backups/`、`dist/`、`config.json`（含本机路径）。
备份与快照由 `wb.py backup` 单独管理，不依赖 git。

## 状态

已可用（MIT 许可）。验证过的 harness 版本：**0.2.1-alpha.1** 与 **0.2.1-rc.3**（两个版本上
`install` 一键装 + 页面 + 接口用例全过）。换新版本先跑 `python tools\wb.py preflight`。

已知限制：跨**机器**尚未验证（目前都是同机多实例）；插件市场的注册表搜索依赖
`awesome-dsh-plugin.com` 的公开 JSON，离线时只能用确切包名安装。

## 许可

MIT，见 [LICENSE](LICENSE)。
