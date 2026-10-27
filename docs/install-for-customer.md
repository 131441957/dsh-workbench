# 客户安装指南（DSH 工作台）

> ⚠️ **本项目由 AI 生成**：代码与文档绝大部分由 AI 编程助手编写，人类负责定需求与验收。
> 请据此判断风险——所有"已验证"的结论都附了可复现的命令。

> 面向**第一次在别的机器上装工作台**的人。装完你会得到一个独立的插件宿主页面，
> 与你的主 harness 隔离，主 harness 只多一个**可摘除**的接入层。

## 0. 你需要什么

- Windows 10/11，已装 **DeepSeek Harness**（工作台不含运行时，会从你的安装复制一份）
- **Python 3.10+**（`python` 在 PATH 里）
- 磁盘：约 **2 GB**（运行时副本 1.65 GB + 其余）
- 端口：默认 **59430**；被占用时会自动换（见第 4 节）

## 1. 装法一：双击（推荐，什么都不用敲）

解压后在目录里双击 **`install.cmd`**（同目录还有 `install.ps1`）→ 弹一个窗口 → 等它跑完 → 回车关闭。

它会自动做完：找 Python → 探测你的 harness → 兼容体检 → 复制运行时 + 建 profile → 同步 API 凭据 →
把接入层装进你的 harness profile（**已装过就跳过**）→ 打印入口地址。

- 想先看会做什么：`powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun`
- 不想动 harness profile：加 `-NoAttach`
- 装完自动开页面：加 `-OpenPage`

## 2. 装法二：一条命令

```powershell
python tools\wb.py setup
```

等价于 `preflight → install → attach`。参数：`--no-attach`（不装接入层）、`--open`（装完开页面）、`-y`（不提示）。

重复跑是安全的：运行时已存在就不会再复制 1.6 GB。

## 3. 装法三：分步（排障/想看清每一步）

解压分发目录后，在**该目录里**执行：

```powershell
python tools\wb.py paths --redetect   # 确认它认对了你的 harness（装错了会复制错运行时）
python tools\wb.py preflight          # 体检：compatible / degraded / incompatible
python tools\wb.py install            # 复制你的 harness 运行时 + 建 bench profile + 起服务
python tools\wb.py attach --apply     # 把接入层（软依赖桥）装进你的 harness profile
python tools\wb.py page               # 打开页面（带 token）
```

- `install` 是幂等的，可以反复跑（修复也用它）
- **`install` 结束前会自己确认注入层是否就绪**；如果第一次没起来，它会自动安全重启一次——所以看到「自动重启一次」是**正常现象**，不是报错
- 整机第一次装大约 **30~60 秒**（大头是 1.6 GB 复制）
- `attach` 不加 `--apply` 是预览：只打印将要对你的 profile 做的改动
- 装完 **重启一次你的 harness**，接入层的工具才会出现（桥是宿主代码）

## 4. 装完怎么确认成功

```powershell
python tools\wb.py status      # 端口在听、看门狗运行中
python tools\wb.py doctor      # 逐项自检
```

浏览器里应该看到：**标签页标题是「DSH 工作台」**，顶部有 `Harness会话 / 插件 / 状态 / 设置`。

## 5. 装完第一件正事：装插件

工作台的价值就在这——**它是插件宿主，装插件不碰你的主 harness**。三条命令：

```powershell
python tools\wb.py plugin-search 记忆          # 搜（读社区注册表，输出可直接安装的 npm 名）
python tools\wb.py plugin-info   <包名>        # 侦察：会露在哪、要什么版本
python tools\wb.py install-plugin <包名|目录>  # 装：依赖+登记+安全重启+验证，失败自动回滚
```

装完**刷新页面，顶栏会自动多一个入口**（不用改任何代码）。

自己写插件也只要三步：复制 `seeds\plugin-template` 改名 → 改三处名字（`package.json` / `cordis.patch.yml` / `client.js` 的 `id`）→ `install-plugin .\plugins\你的插件`。

完整说明（含"为什么装完看不见"、卸干净、升级、回滚）见 **[install-plugins.md](install-plugins.md)**。

## 6. 日常操作（可视化安装器）

桌面「**DSH 工作台 安装器**」（或 `pythonw tools\wb_gui.py`）里有：

| 按钮 | 用途 |
|---|---|
| 安装 / 修复 | 幂等重跑安装 |
| 同步运行时（复制主驾安装） | 主 harness 升级后跟版本（旧的会自动备份，可回滚） |
| 回滚运行时 | 换回上一份运行时副本 |
| **立即备份… / 快照列表 / 还原快照…** | 客户自助备份与还原（推荐改任何东西前先备份） |
| 启动 / 停止 / 打开页面 / 暂停·恢复自动伴随 | 生命周期 |

顶部有一行 **构建信息**（版本 / `wb.py` 更新时间 / 根目录）——找我们排障时先把它截图发来。

## 7. 常见问题

**Q1：端口 59430 被占用？**
不用管：`install` / `start` 会自动往上找一个空闲端口，写进 `config.json`，并打印实际地址（例如 59431）。

**Q2：页面打开是空白的？**
两种常见原因：
1. **重启后 token 变了**——旧的标签页会失败。重新执行 `python tools\wb.py page` 打开新地址。
2. 注入层没加载（极少见，`install` 会自动重试一次）。若仍为空：看 `logs\workbench.err.log` 与 `home\logs\startup-*.log`；`python tools\wb.py fix-ui` 也会检查「页面模块表里有没有各个插件的 client.js」。

**Q3：装了个插件之后工作台起不来了/白屏？**
```powershell
python tools\wb.py start-safe                # 安全模式：只禁用第三方插件，界面还能开
python tools\wb.py uninstall-plugin <包名>   # 在安全模式里卸掉可疑插件
python tools\wb.py restart-safe              # 恢复正常启动
python tools\wb.py restore --from latest     # 或者直接还原最近一份快照
```

**Q4：`attach` 会不会破坏我的 harness？**
它只改**你的 profile 里 `package.json`**（加一条 `link:` 依赖 + 一个 bundle），写之前会备份到 `backups\attach-<时间>\`；`python tools\wb.py detach --apply` 可完全撤销。**不碰安装目录、不碰 app.asar。**

**Q4-2：我不小心点了两次 install 会怎样？**

- **先后点两次**：安全。第二次会走"修复"路径（运行时已存在就跳过复制），约 3 秒结束。
- **同时点两次**（两个窗口一起跑）：第二个会被**安装锁**挡住，提示
  `另一个安装正在进行（pid=…，开始于 …）——等它跑完再点`。等第一个跑完再点即可。
- 万一上次崩了留下锁文件，程序会自动识别"进程已退出"并清掉，不会永久卡住。

**Q5：怎么彻底卸载？**

**最省事：双击包根目录的 `uninstall.cmd`**（默认演练，什么都不动；看清楚后再跑 `uninstall.ps1 -Apply`，
连文件一起删加 `-Purge`，顺带摘接入层加 `-Detach`）。

或者一条命令（默认只演练，看清楚再加 `--apply`）：

```powershell
python tools\wb.py uninstall                        # 演练：列出会停的服务、会删的快捷方式、目录多大
python tools\wb.py uninstall --apply                # 真做：停服务/守护 + 删指向本目录的快捷方式
python tools\wb.py uninstall --apply --purge        # 连目录一起删（几秒后自己消失）
python tools\wb.py uninstall --apply --purge --detach   # 顺带把接入层从你的 harness profile 摘掉
```

要点：

- **只删指向本目录的快捷方式**，多套工作台共存时不会误删别人的入口
- `--detach` 会改你的 harness profile（摘掉桥），需要**重启那个 harness** 才生效
- `--purge` 不自删自己：它写一个临时脚本，延迟 2 秒把整个目录删掉

手工等价操作（万一命令跑不了）：

```powershell
python tools\wb.py detach --apply    # 摘接入层
python tools\wb.py suspend           # 停服务与自动伴随
# 手动删掉桌面「DSH 工作台」「DSH 工作台 安装器」+ 启动项「DSH 工作台（自动伴随）」
# 最后删掉整个工作台目录（它自带运行时副本，不在系统里留东西）
```

## 8. 这套东西的边界

- **适用范围**：面向 **自研插件** 与 **非会话类插件**（面板 / 设置分区 / 浮层都能显示）。
- **会话类插件不在范围内**：`conversation.*`（`conversation.chat.*` / `conversation.composer*` / `conversation.input.*` …）
  与 `composer.*` 绑定真实会话上下文，且客户端 API 只允许插件层渲染 `root` 槽位
  （`child slots render through the component props face`）→ 这类插件请装在 DSH 本体里。
- **适用版本**：针对 **DeepSeek Harness 0.2.1-rc.3** 验证与分发；`0.2.1-alpha.1` 同样实测可用。
  换版本先跑 `python tools\wb.py preflight`。
- 工作台**不接 agent**：它是插件宿主，没有自己的会话界面；会话视图读的是主 harness 的会话（只读 + 投递）。
- 排查"插件装了但界面不显示"：页面控制台跑 `__wbSlotsInventory().missingHost`，列出的就是没有宿主的槽位。
- 分发包**不含测试插件**（如插件市场），也不含运行时/日志/备份。
- 主 harness 里只有接入层一个插件（软依赖）；它挂了也不会拖垮主 harness。

## 9. 目录说明

| 路径 | 内容 |
|---|---|
| `app/` | 复制来的运行时副本（可 `sync-app` 重建，所以不进备份） |
| `home/` | 工作台自己的 DSH_HOME（`profiles/bench`） |
| `plugins/` | 4 个插件：界面注入、会话视图、状态面板、接入层 |
| `ui/` | 界面改造（改这里就是改 webui，见 `ui/README.md`） |
| `state/` `logs/` `backups/` | 运行状态、日志、快照（`wb.py backup` 生成的 zip） |
