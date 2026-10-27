# 改工作台 WebUI（给接手的人）

> 一句话：**不要 fork 源码、不要改安装目录**。界面是在运行时注入的：
> `plugins\dsh-wb-ui` 用 `webServer.tapIndex(html => html)` 把 `ui\workbench.css` 和 `ui\workbench.js`
> 塞进首页，刷新即生效，删文件即还原。

```
DSH 首页 ──tapIndex 改写──> 注入 <link css> + <script js>
                              ├─ ui/workbench.css  布局与外观
                              └─ ui/workbench.js   顶栏、遮罩、设置裁剪、自诊断
```

## 0. 30 秒上手

| 想做什么 | 改哪儿 |
|---|---|
| 换配色 / 间距 / 水印 | `ui\workbench.css`（第三、四节，有注释） |
| 顶栏顺序、默认面板 | `ui\workbench.js` 的 `LEFT_ORDER` / `RIGHT_ORDER` / `DEFAULT_PANEL` |
| 隐藏某块原版界面 | `ui\workbench.js` 的 `HIDE_TEXTS`（按**叶子标题文字**，不要按类名） |
| 设置页保留哪些分区 | `state\ui-config.json` 的 `keepNav`（`wb.py install-plugin` 会自动写） |
| 加一个新面板 | **不要改 ui**：复制 `seeds\plugin-template` 写插件 |

改完刷新页面。只有改了「宿主侧」代码（`plugins\*\index.js`）才需要 `wb.py restart-safe`。

## 1. 必须先懂的一件事：类名会变

DSH 前端是 CSS-in-JS，类名 = **每版本重新生成的 hash 前缀** + 稳定语义后缀：

| 版本 | frame | sidebarCol | centerCol |
|---|---|---|---|
| 0.2.1-alpha.1 | `OSewFq_frame` | `OSewFq_sidebarCol` | `OSewFq_centerCol` |
| 0.2.1-rc.3 | `mP3x-q_frame` | `mP3x-q_sidebarCol` | `mP3x-q_centerCol` |

所以：

- **CSS 里一律用后缀匹配**：`[class*="_frame"]`、`[class*="_sidebarCol"]`……
- **JS 里一律用后缀匹配**：`[class*="_panelRow"]`；`workbench.js` 顶部备好了两个helper：
  `bySuffix('frame')` / `allBySuffix('navCell', root)`，新代码直接用它们，别自己拼选择器
- 写死前缀（`.OSewFq_frame`）的写法在换版本后会**静默失效**——不报错，只是布局回到原版。
  2026-10-27 就是这样踩的：rc.3 上 frame 仍是 grid，左侧留白 280px；同时遮罩与设置裁剪也全都悄悄不工作。

## 2. 怎么验证你改的东西生效了

页面每次加载 4.6 秒后会把自诊断写到 `state\boot-diag.json`，关键字段：

| 字段 | 含义 |
|---|---|
| `shellClasses.frame` / `.sidebarCol` / `.centerCol` | 当前版本真实的类名（带前缀） |
| `shellClasses.cssFrameApplied` | `flex` = 你的布局 CSS 命中了；`grid` = 没命中 |
| `sidebarVisibleRows` | 原版侧栏还剩几行是可见的，**0 = 藏干净** |
| `topbarTabs` / `discovered` | 顶栏最终顺序 / 扫到的入口 |
| `hasPanel`、`errors` | 我们的面板是否挂上、页面有没有 JS 报错 |

不想开浏览器手动看的话：

```powershell
python tools\probe-ui.py --root .              # 主工作台
python tools\probe-ui.py --root E:\WB-<版本>    # 测试床（换成你自己的床根目录）
```

它会用一个**独立 profile** 的 Edge 窗口加载一次页面、读回上面这些字段再关掉（不截屏、不碰你正在用的窗口）。

浏览器控制台里还有几个钩子：

| 名字 | 作用 |
|---|---|
| `__WB_UI__` | 注入层状态（隐藏了什么、遮罩、上次点击日志） |
| `__wbSweep()` | 立刻重跑一次扫描/隐藏/裁剪 |
| `__wbProbeSettings()` | 开设置→裁剪→导出结构到 `state\settings.html`→关掉 |
| `__wbSnapshot('tag')` | 把 DOM（标签/类名/位置/尺寸）POST 到 `state\dom-snapshot.json` |

## 3. CSS 文件结构（`ui\workbench.css` 里都有对应注释）

| 段 | 内容 | 能不能删 |
|---|---|---|
| 一、布局骨架 | 侧栏/空右栏不占位、frame 改 flex、中列撑满、藏拖拽手柄 | 删了会回到原版三列布局 |
| 二、设置页 | 收掉标题与actions、压窄导航列 | 删了设置页恢复原版外观 |
| 三、示例 | 右下角水印、字体微调 | 随便删 |
| 四、配方 | 主题变量、隐藏技巧、加面板的指路 | 是注释 |

**两条禁令**（都踩过）：

1. 不要把设置页导航列整列 `display:none` → 插件在设置里加的分区会全部点不进去
2. 不要给设置面板加 `left`/`transform` 做居中 → 它不一定是绝对定位，会被平移出屏幕

## 4. 顶栏是怎么长出来的（`ui\workbench.js`）

1. `scanSidebarEntries()` 扫 `[class*="_panelRow"]` → 得到「标签 + 元素」
2. `LEFT_ORDER = ['Harness会话','插件']`、`RIGHT_ORDER = ['状态','设置']` 决定左右与顺序；
   **不在名单里的入口自动排到左边末尾** → 新插件不用改代码
3. `设置` 不是面板行，用 `findButton('设置')` 兜底；**rc.3 把设置收进了「更多」菜单**，
   所以 rc.3 上顶栏是「更多」而不是「设置」——这是如实反映该版本界面
4. `maskUnknownMain()` 在面板就位前藏住主区（避免原版落地页闪一下），6 秒上限
5. `pruneSettings()` 按叶子标题文字裁剪设置分区，白名单来自 `/wb-ui/config`

### 4.1 插件自带「设置分区」也会变成顶栏按钮（2026-10-27）

插件除了注册 `sidebar.panellist` 当面板，还可能只往**设置页**里加一个分区
（`settings.section`，例如 `dsh-pet` 的「桌宠配置」）。这种分区原来只能从「设置 → 左侧导航」
进去，不在顶栏。现在：

- 打开过一次设置后，`discoverSettingsSections()` 会扫左侧导航（`*_navCell`），
  把**不在内置名单**（`BUILTIN_SETTINGS_NAV`：通用设置 / 模型 / 内置插件 / Agent 预设 …）里的
  标题当成"插件分区"，**自动加一个顶栏按钮**（`data-wb-kind="settings"`）
- 点它 = 打开设置并切到该分区（`openSettingsSection()`）
- 同时把这些分区从设置左侧导航里**隐掉**（提到顶栏了，不再重复列）
- 发现结果会 POST 回 `/wb-ui/config` 落进 `state\ui-config.json`，
  这样**下次打开页面不用先点设置**也有按钮

重名的情况（同一插件既有面板又有设置分区，比如「插件市场」）：面板优先，不会出两个按钮。
换 DSH 版本后如果内置分区改名，见到顶栏多出 `模型`/`模板` 这类按钮，就把它补进
`BUILTIN_SETTINGS_NAV`。

## 5. 加一个面板（推荐做法，不用改 ui）

```powershell
Copy-Item .\seeds\plugin-template .\plugins\dsh-wb-demo -Recurse
# 改三处：package.json 的 name、cordis.patch.yml 的 name、client.js 的 id（必须等于包名）
python .\tools\wb.py install-plugin .\plugins\dsh-wb-demo
```

装完顶栏自动多一个入口。`client.js` 的 `id` 与包名不一致会让**整个客户端白页**
（`Failed to load plugins`），`install-plugin` 现在会提前拦住。

## 6. 出问题怎么回到原样

| 症状 | 处理 |
|---|---|
| 界面全白 / `Failed to load plugins` | 看 `state\boot-diag.json` 的 `errors`；`.client.js` 的 `id` 对不对 |
| 布局回到原版三列 | 你的 CSS 选择器写死了前缀 → 改成 `[class*="_xxx"]`，看 `cssFrameApplied` |
| 原版左栏露出来 | 看 `sidebarVisibleRows`；`workbench.js` 的 `findSidebarChain()` 锚点是否拿到 |
| 想彻底还原 | 删 `ui\workbench.css` + `ui\workbench.js`，或 `wb.py suspend` 停掉整套 |
