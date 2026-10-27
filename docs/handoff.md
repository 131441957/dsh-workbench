# 工作台项目 · 新会话接手提示词

> 用法：把「=== 复制开始 ===」到「=== 复制结束 ===」之间原样发到新会话开头。

=== 复制开始 ===

接着做「DSH 工作台」项目（`E:\DSH-WORKBENCH`）。先按这个顺序补上下文：

1. `memory_project("workbench")` —— 项目全景（记忆库跨工作区共享，别乱改）
2. 本文件 `docs\handoff.md` —— 你现在读的这份
3. `docs\compat-matrix.md`（哪些 harness 版本能跑）+ `docs\webui-guide.md`（怎么改界面）
4. 改代码前先看**文件头注释**——每个文件的头两屏都写了「它干什么 / 为什么这么写 / 怎么验证」

## 一句话背景
用户怕改坏主 harness，所以做了一套「工作台」：`E:\DSH-WORKBENCH` 里一份**独立整套** DSH 运行时
（自己的 DSH_HOME、profile=bench、端口 59430，不接 agent），插件全装这里；主 harness（`E:\SSS` + `E:\DSH\home`）
**只读不动**，两边靠「接入层」通信。目标是**能分发给客户装到别的 harness 上**。

## 铁律（每条都踩过）
1. **主 harness 一个字节都不许改**：`E:\SSS`、`E:\DSH\home`（尤其 `profiles\desktop\*`）只读。
   唯一例外：`attach/detach` 改**目标** profile 的 `package.json`，且默认干跑、要 `--apply`。
2. **绝不重装主 harness**；工作台「同步运行时」只是把主驾当前安装**复制**到 `app\`。
3. **根目录一律从自身位置推导**（`__file__` / `import.meta.url`），不许写死——本机并存主套与测试床。
4. **前端类名只按后缀匹配**：DSH 用 CSS-in-JS，前缀每版本重生成（alpha.1=`OSewFq_`，rc.3=`mP3x-q_`），
   写死前缀会**静默失效**（布局回原版、遮罩/设置裁剪悄悄不工作）。CSS 用 `[class*="_frame"]`，
   JS 用 `bySuffix()/allBySuffix()`。
5. **判断可见性/文本用 `textContent`，不要 `innerText`**（被 visibility 藏住的元素没有 innerText）。
6. **隐藏清单别吃自己**：`HIDE_TEXTS` 不要放自己会用的文字，遍历时跳过 `#wb-topbar`。
7. **改桥或宿主插件要重启对应 harness**；改 `ui/` 只要刷新页面。
8. **杀进程按 `ExecutablePath` 过滤，绝不按 `CommandLine`**（命令行里带 cwd，会误杀工具助手）。
9. **操作桌面不盲点**：先确认窗口再动手；能用 `boot-diag` / HTTP / 日志验证的就不碰屏幕。
10. **说"能用"必须有运行时证据**：端口在听 + `/wb-ui` 认领 + 页面模块表 + `boot-diag` 无报错。
11. 改代码用编辑工具，别用 PowerShell 拼字符串；改完 `node --check` / `python -m py_compile` 复核。

## 现在的状态（2026-10-27，功能面已清空）

**工具链** `tools\wb.py`（3200 行，纯标准库）：
- 装与修：`install`（含 preflight 门禁 + 首启自愈）｜`sync-app`｜`rollback`
- 启与停：`start`｜`stop`｜`restart`｜`restart-safe`｜`suspend`｜`resume`｜`start-safe`（只禁第三方插件）
- 状态：`status`｜`info`（机器可读 JSON）｜`doctor`｜`paths`｜`caps`｜`compat`｜`watch`｜`api`｜`logs`
- 备份：`backup --note`｜`backups [--json]`｜`restore --from`
- 插件：`plugin-info`｜`install-plugin`（装前快照 + 失败回滚 + 模块 id 闸门）｜`uninstall-plugin`｜`fix-ui`｜`plugin-search`｜`plugin-update [--apply]`
- 体检：`preflight --install <目录>` —— 三档 `compatible / degraded / incompatible`
- 接入：`attach/detach`（把桥装进目标 harness 的 profile，默认干跑）
- 分发：`pack`｜`prepublish`｜`registry [--refresh]`｜`sync-bed <根目录>`

**四个插件**（都在 `plugins\`，每个文件头部有路由表/渲染说明/验证命令）：
- `dsh-wb-ui`：注入层（tapIndex 改首页 + 标题 + 三条 `/wb-ui` 路由）
- `dsh-wb-sessions`：「Harness会话」面板（代理到主驾桥；**自己渲染 Markdown**）
- `dsh-wb-api-browser`：「插件」+「状态」两个面板（插件台账 + 社区注册表 + 活体快照 + 备注）
- `dsh-workbench-bridge`：**唯一装在主 harness 的插件**（软依赖），`/wb-bridge/*` + 四个 `workbench_*` 工具

**界面**：`ui\workbench.js`（顶栏动态发现 + 遮罩 + 设置裁剪 / 741 行，头部有 `[A]~[J]` 结构图与 boot 时间线）
+ `ui\workbench.css`（逐段注释，跨版本后缀选择器）。改界面读 `docs\webui-guide.md`。

**两个实例并存**：主套 `59430`（含测试插件 dshmarket）与 rc.3 测试床 `59480`（客户镜像，无 market）。
两者都是 headless（`dsh.cmd` node 模式），不占 Electron 单实例锁、不用 cookie profile。

## 分发与公开
- 打给客户：`wb.py pack --force` → `dist\DSH-Workbench-<版本>\`；硬指标 `MANIFEST.absolutePathHits` 必须 **0**
- 测试插件永不进包（`testOnlyPlugins` 声明）；内部文档按前缀排除
- 私有仓：`https://github.com/131441957/dsh-workbench`（**已推送**，推送需走本机代理 127.0.0.1:10808，
  已写进该仓库的 git 配置）
- **公开前三关**：`wb.py prepublish` 退出码 0 → 处理 `ref/` 历史（filter-repo 或确认授权）→ 决定 LICENSE

## 跨版本（这是"能不能给客户"的核心）
已实测：**0.2.1-alpha.1 ✅**（日常）、**0.2.1-rc.3 ✅**（测试床）。
换任何新版本照这个来：`wb.py preflight --install <目录>` → 看三档结论 → 复制分发包到新根 →
`paths --redetect --install <目录> --home <新根>\home` → 改端口 → `install` → `status`。
改完主套代码要 `wb.py sync-bed <床根>` 同步，否则床里跑的是旧代码。

## 常用验证（不要靠猜）
```powershell
python tools\test-http.py --bridge      # 接口 + 桥 17 项（含无 token 应 401）
python tools\probe-ui.py --root .       # 页面自报：cssFrameApplied 必须 flex、sidebarVisibleRows 必须 0
node tools\test-markdown.mjs            # 会话面板 Markdown 渲染
node tools\test-sessions-group.mjs      # 分组回归（组头必须是工作区名）
node tools\test-plugin-notes.mjs        # 插件备注行数据
node tools\test-capabilities.mjs        # 能力声明合法性
python tools\wb.py doctor|status|info|preflight
python tools\wb_gui.py --selftest       # 安装器不崩
```
`state\boot-diag.json` 每次页面加载 4.6 秒后自动写：`shellClasses`（真实类名 + `cssFrameApplied`）、
`sidebarVisibleRows`、`topbarTabs`、`discovered`、`hasPanel`、`errors`。

## 待办（真实剩余）
1. **跨机器验证**：目前所有验证都是同机多实例，没在第二台机器上跑过 `install → attach → 页面`
2. **公开收尾**：`ref/` 历史清理 + LICENSE（见上）
3. 可选：细粒度会话事件推送（现在只有 3 秒 tick 汇总）
4. 可选：`dshmarket` 只是测试插件，要不要长期留着由用户定

## 用户偏好
中文、简短、要证据不要"应该可以"；改完必须运行时验证；重要节点主动 `wb.py backup`（旧快照一律不删）；
不确定就报告别闷头猜；**别让他手动点窗口**——能用脚本/接口就自己来；出错必须汇报并写进记忆。

=== 复制结束 ===
