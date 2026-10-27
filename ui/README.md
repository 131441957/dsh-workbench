# 工作台界面改造说明（和 harness 改 webui 同一套机制）

工作台的界面不是 fork 源码，而是在**运行时注入**：

```
你的 harness 首页 ──(dsh 原生)──> 工作台 app 副本
                                   └─ plugins\dsh-wb-ui 用 webServer.tapIndex 改写 index.html
                                        ├─ 注入 ui\workbench.css
                                        └─ 注入 ui\workbench.js
```

- `tapIndex(html => html)` 是 DSH 给插件用的首页改写钩子，纯字符串操作；工作台用它把 CSS/JS 塞进 `</head>` 和 `</body>` 前。
- **不修改安装目录里任何文件**：删掉 `ui\workbench.css` / `ui\workbench.js`，或停用 `dsh-wb-ui`，界面立刻恢复原版。
- 页面刷新即生效（`wb.py restart` 不需要，除非改了宿主侧 `index.js`）。

## 你可以改什么

`ui\workbench.css`
- 布局（`.OSewFq_frame` 强制 flex、隐藏 sidebar/rightbar、centerCol 撑满）
- 主题细节、水印（`body::after`，端口用 `var(--wb-port)`）
- ⚠️ 不要把 `.ZCYAFq_nav` 整列 `display:none`：插件的设置分区会全部不可达（踩过）

`ui\workbench.js`
- 顶栏：面板清单是**动态发现的**（扫侧栏 `*_panelRow`），`LEFT_ORDER` / `RIGHT_ORDER` 只决定顺序与左右；新插件不用改代码
- 首帧遮罩 `maskUnknownMain()`：面板就位前藏住主区，避免「探索未至之境」闪一下
- 设置页裁剪 `pruneSettings()`：白名单从 `/wb-ui/config` 读（`state\ui-config.json`，由 `wb.py install-plugin` 写入）
- 开机自诊断：每次加载 4.6 秒后写 `state\boot-diag.json`（按钮表 / hasPanel / clickLog / JS 报错）

## 调试入口（浏览器控制台）

| 名字 | 作用 |
|---|---|
| `__WB_UI__` | 注入层状态（隐藏了什么、遮罩是否生效、上次点击日志） |
| `__wbSweep()` | 立刻重跑一次扫描/隐藏/裁剪 |
| `__wbProbeSettings()` | 打开设置→裁剪→把结构导出到 `state\settings.html`→关闭 |
| `__wbSnapshot('tag')` | 把当前 DOM（标签/类名/位置/尺寸）POST 到 `state\dom-snapshot.json` |

## 想做成别的样子

- 只改外观 → 改 `workbench.css`
- 换导航方式（顶栏/侧栏/命令面板）→ 改 `workbench.js` 里 `placeTopbar` / `buildTopbar` / 扫描逻辑
- 想加自己的面板 → 别改 `ui\`，写个插件（`seeds\plugin-template`），注册 `sidebar.panellist` + `main` 即可
