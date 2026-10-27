# 客户安装指南（DSH 工作台）

> 面向**第一次在别的机器上装工作台**的人。装完你会得到一个独立的插件宿主页面，
> 与你的主 harness 隔离，主 harness 只多一个**可摘除**的接入层。

## 0. 你需要什么

- Windows 10/11，已装 **DeepSeek Harness**（工作台不含运行时，会从你的安装复制一份）
- **Python 3.10+**（`python` 在 PATH 里）
- 磁盘：约 **2 GB**（运行时副本 1.65 GB + 其余）
- 端口：默认 **59430**；被占用时会自动换（见第 4 节）

## 1. 三步装好

解压分发目录后，在**该目录里**执行：

```powershell
python tools\wb.py install          # 复制你的 harness 运行时 + 建 bench profile + 起服务
python tools\wb.py attach --apply   # 把接入层（软依赖桥）装进你的 harness profile
python tools\wb.py page             # 打开页面（带 token）
```

- `install` 是幂等的，可以反复跑（修复也用它）
- **`install` 结束前会自己确认注入层是否就绪**；如果第一次没起来，它会自动安全重启一次——所以看到「自动重启一次」是**正常现象**，不是报错
- 整机第一次装大约 **30~60 秒**（大头是 1.65 GB 复制）
- `attach` 不加 `--apply` 是预览：只打印将要对你的 profile 做的改动

## 2. 装完怎么确认成功

```powershell
python tools\wb.py status      # 端口在听、看门狗运行中
python tools\wb.py doctor      # 逐项自检
```

浏览器里应该看到：**标签页标题是「DSH 工作台」**，顶部有 `Harness会话 / 插件 / 状态 / 设置`。

## 3. 日常操作（可视化安装器）

桌面「**DSH 工作台 安装器**」（或 `pythonw tools\wb_gui.py`）里有：

| 按钮 | 用途 |
|---|---|
| 安装 / 修复 | 幂等重跑安装 |
| 同步运行时（复制主驾安装） | 主 harness 升级后跟版本（旧的会自动备份，可回滚） |
| 回滚运行时 | 换回上一份运行时副本 |
| **立即备份… / 快照列表 / 还原快照…** | 客户自助备份与还原（推荐改任何东西前先备份） |
| 启动 / 停止 / 打开页面 / 暂停·恢复自动伴随 | 生命周期 |

顶部有一行 **构建信息**（版本 / `wb.py` 更新时间 / 根目录）——找我们排障时先把它截图发来。

## 4. 常见问题

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

**Q5：怎么彻底卸载？**
```powershell
python tools\wb.py detach --apply    # 先摘接入层
python tools\wb.py suspend           # 停服务与自动伴随
# 然后删掉整个工作台目录即可（它自带运行时副本，不在系统里留东西）
```

## 5. 这套东西的边界

- 工作台**不接 agent**：它是插件宿主，没有会话界面。因此**只挂在会话界面上的插件**（消息操作、输入框、悬浮层）装进去功能在、界面看不见——`install-plugin` 会提前告警。
- 分发包**不含测试插件**（如插件市场），也不含运行时/日志/备份。
- 主 harness 里只有接入层一个插件（软依赖）；它挂了也不会拖垮主 harness。

## 6. 目录说明

| 路径 | 内容 |
|---|---|
| `app/` | 复制来的运行时副本（可 `sync-app` 重建，所以不进备份） |
| `home/` | 工作台自己的 DSH_HOME（`profiles/bench`） |
| `plugins/` | 4 个插件：界面注入、会话视图、状态面板、接入层 |
| `ui/` | 界面改造（改这里就是改 webui，见 `ui/README.md`） |
| `state/` `logs/` `backups/` | 运行状态、日志、快照（`wb.py backup` 生成的 zip） |
