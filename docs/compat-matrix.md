# 兼容矩阵：工作台能在哪些 harness 版本上跑

> 工作台自带一份**运行时副本**，所以“能不能用”取决于目标版本提供不提供它需要的**服务、槽位、客户端包**。
> 静态判断用 `wb.py preflight --install <目录>`（读 `runtime.json` + 在 `app.asar` 里数标记），
> 动态确认靠“开来一套床 + 跑 install”。

## 三档结论（`wb.py preflight`）

| 档位 | 含义 | 退出码 | 处置 |
|---|---|---|---|
| `compatible` | 服务/槽位/客户端包齐全 | 0 | 正常装 |
| `degraded` | 能跑，但列出的功能会缺 | 0 | 照装，`install` 会先把降级项打出来 |
| `incompatible` | 缺注入层或顶栏入口依赖 | 1 | `install` 直接中止（`--force` 可试装） |

阻断项（缺了就是白页）：

- `webServer` —— 注入层与状态面板靠它挂路由
- `sidebar.panellist` —— 顶栏入口靠它注册

降级项（缺了只是少功能）：

| 缺失 | 影响 |
|---|---|
| `sessionController` | 「Harness会话」面板不可用（列表/历史/发送） |
| `reflect` | 状态面板的「宿主服务」实时枚举不可用（只剩静态快照） |
| `settings.section` | 插件在设置页里的分区不出现（插件市场等设置入口看不见） |

机器可读：`wb.py preflight --install <目录> --json` →
`{grade, version, blockers[], degradations[], notes[], checks[], pluginNavigation{present,entryCustomization}}`

## 已验证

| harness 版本 | 安装位置 | 结论 | 证据 |
|---|---|---|---|
| **0.2.1-alpha.1** | `E:\SSS`（主驾） | ✅ 可用 | 3 自研插件加载、面板齐全、页面标题正确；日常在用 |
| **0.2.1-rc.3** | `E:\SOS`（官方安装，仅作运行时来源） | ✅ 可用 | 独立床 `E:\WB-RC3`（端口 59480、自家 home）：`boot-diag` 显示 `插件/状态/Harness会话` 全部挂载，`wb-api/*` 全通，`wb.py api` 采到 303 行 / 5 层 |

## 已知差异（换版本时必须检查）

| 项 | alpha.1 | rc.3 | 影响 |
|---|---|---|---|
| `dsh-client-ui-entry-customization` | 无 | **有** | rc.3 里它依赖 `pluginNavigation`（原版插件管理器提供）。**禁用 `ui-plugin-manager` 会让客户端整页报 `Failed to load plugins: 1 entry did not activate`** —— 这就是第一个“换版本就白页”的坑，已改成不禁用它 |
| 服务/槽位 | webServer、sessionController、reflect、`sidebar.panellist`、`settings.section` | 同左 | 齐全 |
| 补丁里的未知 entry id | 只警告 | 只警告 | 实测 `patch: entry "xxx" not found`，**exit 0**，不会启动失败 → 补丁可跨版本复用 |

## 测试床怎么开（换任何版本都照这个来）

```powershell
# 1) 静态体检（不复制、不启动，秒级）
python tools\wb.py preflight --install "<目标安装目录>"

# 2) 复制分发包到新根，作为独立床
Copy-Item dist\DSH-Workbench-<版本> E:\WB-<版本> -Recurse

# 3) 指向目标安装 + 自己的 home + 独立端口
set DSH_WORKBENCH_ROOT=E:\WB-<版本>
python tools\wb.py paths --redetect --install "<目标安装目录>" --home "E:\WB-<版本>\home"
#    再改 config.json 的 port（例如 59480）

# 4) 装（会复制运行时；首次约 30~60 秒，会自动确认注入层）
python tools\wb.py install

# 5) 验证：端口在听、/wb-ui 的 uiDir 是自己的、3 个插件都在
python tools\wb.py status
```

**床存在的意义是“验当前开发态”**，所以改完主套代码要同步过去，否则床里是旧代码：

```powershell
python tools\wb.py sync-bed "E:\WB-<版本>"     # 只比对内容，幂等；同步后到床里 restart-safe
```

## 注意

- **0.2.1-rc.3 把「设置」收进了「更多」菜单**：顶栏因此显示「更多」而不是「设置」——这是如实反映该版本界面，不是故障。
- 因此**藏原版侧栏不能只靠「设置」按钮当锚点**（rc.3 没有这个按钮，会让原版左栏整条露出来）。现在 `ui\workbench.js` 的 `findSidebarChain()` 在找不到「设置」时退回“任意一个 `*_panelRow`”当锚点；`boot-diag.json` 新增 `sidebarVisibleRows` 字段（0 = 藏干净），换版本时先看这个数字。
- 床要 `--no-watchdog` 起（看门狗跟踪的是主驾**当次**启动的监听 pid，主驾一重启就把床关掉）。
- 两套工作台可以同时开：它们都是 headless（`dsh.cmd` node 模式），不占 Electron 单实例锁、不用 `%APPDATA%` 的 cookie profile。
- 床与主套共享的只有主 harness home 的**只读**用途（同步 `.credentials.yaml`、读 `storages\workspace.json`）。
