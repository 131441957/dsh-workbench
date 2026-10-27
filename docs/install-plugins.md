# 装插件（工作台的核心用法）

> 工作台 = 插件宿主。装插件不碰你的主 harness，也不会改工作台代码——**装完顶栏自动出现入口**。

## 0. 前提

工作台已经跑起来（`python tools\wb.py status` 能看到端口在听）。下面命令都在**工作台根目录**执行。

## 1. 装社区里已有的插件

```powershell
# ① 搜（读的是社区注册表，不依赖插件市场那个插件）
python tools\wb.py plugin-search 记忆 --limit 10

# ② 侦察（只读，不安装）：会露在哪、注册了哪些槽位、需要什么 peer 版本
python tools\wb.py plugin-info <npm 包名>

# ③ 装（一条命令做完：装依赖 → 认界面入口 → 登记设置白名单 → 安全重启 → 验证；失败自动回滚）
python tools\wb.py install-plugin <npm 包名>
```

⚠️ **市场里显示的短名 ≠ npm 包名**。比如卡片上写 `dsh-message-ops`，真名是 `@240xu/dsh-message-ops`。
`plugin-search` 打印的就是**可以直接装**的 npm 名，用它。

国内网络建议先设镜像：
```powershell
$env:npm_config_registry = "https://mirrors.cloud.tencent.com/npm/"
```

## 2. 装本地插件（自己写的、或别人发给你的目录）

```powershell
python tools\wb.py install-plugin "D:\some\my-plugin"      # 传目录
```

目录里至少要有：`package.json`（`dsh.bundle.patch` + `dsh.client`）、`index.js`（宿主半）、
`client.js`（界面半，可选）、`cordis.patch.yml`（entry 声明）。

## 3. 从零造一个插件（复制模板，5 步）

```powershell
# ① 复制模板
Copy-Item .\seeds\plugin-template .\plugins\dsh-wb-demo -Recurse

# ② 改三处名字（缺一不可）
#    · package.json       "name": "dsh-wb-demo"
#    · cordis.patch.yml    - id: wb-demo  /  name: 'dsh-wb-demo'
#    · client.js          __ModuleLoader__.load({ id: 'dsh-wb-demo' … })   ← 必须等于包名！

# ③ 装（会自动登记、重启、验证）
python tools\wb.py install-plugin .\plugins\dsh-wb-demo
```

`client.js` 里的 `id` 与包名不一致时，浏览器会整页报 `Failed to load plugins`（白屏）。
`install-plugin` 现在会在**装之前**静态检查这一条并拒绝，附上改法。

模板里已经写好：注册 `sidebar.panellist` + `main` 两处槽位 → 顶栏自动多一个入口。
具体写法/可改项见 `seeds\plugin-template\README.md`。

## 4. 装完怎么确认真的生效

```powershell
python tools\wb.py plugins list        # profile 里有哪些插件（bundle / linked / spec）
python tools\probe-ui.py --root .      # 页面自报：topbarTabs 里应该出现新入口、errors 必须为 0
```

或者直接看页面：顶部多一个按钮 / 「插件」面板里多一行（带版本、来源、能力、上次验证时间）。

> `install-plugin` 自己会验证三件事：profile 里 bundle+linked、页面模块表含 `<包>/client.js`、
> 本次启动没有 EADDRINUSE / startup failed。验证不过会**自动回滚**到装前状态。

## 5. 日常维护

```powershell
python tools\wb.py plugin-update                 # 看哪些插件有新版本
python tools\wb.py plugin-update <包名> --apply  # 升级单个（同样走快照 + 验证 + 失败回滚）
python tools\wb.py uninstall-plugin <包名>        # 卸干净：profile / node_modules / 设置白名单 / 台账
python tools\wb.py fix-ui                        # 界面没出现入口时，重扫并补登记
```

## 6. 常见坑

| 现象 | 原因 / 处理 |
|---|---|
| 装完顶栏没变化 | 有些插件只注册 `conversation.*` / `chat.*` / `composer.*` / `shell.overlay` 槽位——工作台**没有会话界面**，装进去功能在但看不见。`install-plugin` 会提前告警 |
| 页面白屏 `Failed to load plugins` | 插件的 `client.js` 模块 id ≠ 包名；或插件版本与宿主不兼容。先 `wb.py uninstall-plugin <包名>` |
| 装完工作台起不来了 | `python tools\wb.py start-safe`：只禁用第三方插件、保留内置+自研三个，界面还能开；进去卸掉可疑插件，再 `wb.py restart-safe` |
| 装的时候说要 `--keep-nav` | 该插件在设置页加了分区；不登记的话分区会被界面裁剪掉。`install-plugin --keep-nav <标题>` |
| 装完要我重启主 harness？ | **不需要**。工作台插件只影响工作台；只有主驾侧的接入层（`attach/detach`）才要重启主 harness |

## 7. 权限模式的影响（agent 替你操作时）

工作台**不依赖 agent**，它自己跑得好好的；这里说的是「让 agent 帮你装插件 / 改界面」时能不能成。

| 操作 | `workspace-write`（工作区内修改） | 说明 |
|---|---|---|
| 打开工作台页面、看面板 | ✅ | 与沙箱无关 |
| agent 调 `workbench_*` 工具（status/api/plugins/call） | ✅ | 工具在 harness 宿主进程里跑，走 localhost HTTP；沙箱只管 shell 的文件访问 |
| `wb.py status` / `info` / `plugins list` | ✅ | 只读命令不受限 |
| **`install-plugin` / `uninstall-plugin` / `plugin-update`** | ❌（多数情况） | 要写 `<工作台根>\home\profiles\bench\**` 与 `state\**`；若工作区不包含工作台根，会被拒 |
| 改 `ui\` / `plugins\` 源码、`sync-bed` / `backup` / `restore` | ❌（多数情况） | 同上，都是工作区外写 |

依据：`dsh-bash-sandbox` 的说明写的是「使其**文件访问**受到限制……**网络访问和进程可见性不在其保证范围内**」。
所以"用"没问题，"改"要看工作区在哪。

**想让 agent 在 `workspace-write` 下也能装插件，三种做法（由省事到麻烦）：**

1. 把会话的工作区设为**工作台根目录**（`<工作台根>`），这样写 `home\ state\ ui\ plugins\` 都在工作区内 → 全部可用
2. 需要装插件时另开一个工作区在工作台根的会话
3. 该次操作临时提升到 `danger-full-access`（最省事也最危险，不推荐长期这么用）

**已经做过的降级处理**（所以受限模式下不会"装到一半炸掉"）：

| 会写到工作区外的动作 | 受限时的行为 |
|---|---|
| 创建桌面/开机自启快捷方式 | 只**警告**并继续，工作台照样装好；要入口就 `wb.py page` 或到完全权限下再跑一次 `install` |
| 卸载时的临时清理脚本（写 `%TEMP%`） | 退到 `<工作台根>\state\` 写；再不行就提示你手动删目录 |
| 页面探针的 Edge 临时 profile | 同样退到 `<工作台根>\state\` |

所以正确的心智模型是：**工作台本体永远是独立的、随时可用；权限只决定「agent 能替你改多少」。**

## 8. 插件装在哪（为什么不会污染主 harness）

- 装进工作台自己的 profile：`home\profiles\bench\package.json`（`link:` 本地目录 / npm 版本号）
- 依赖落在 `home\profiles\bench\node_modules\`
- 台账在 `state\installed.json`（包名/版本/来源/时间/客户端入口/槽位）
- **主 harness（`E:\SSS` + 你的 `DSH_HOME`）完全不动**
