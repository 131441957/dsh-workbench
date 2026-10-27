# 插件管理器缺口台账

- 建立：2026-10-27
- 范围：工作台的「插件管理」能力（安装 / 卸载 / 治理 / 分发），不含会话面板与接口浏览器本身
- 状态口径：`待做` / `部分` / `已完成` / `不做（有理由）`

## 0. 两条新增硬约束（用户 2026-10-27 定）

1. **插件市场（dshmarket）只是测试插件**，不一定会长期使用 → **不得成为工作台的运行依赖**；如果将来借用它的界面观感，只保留素材/参考，不 pin 依赖、不在架构里给它留位置。
2. **工作台最终要能被客户独立安装到其他 harness 上** → 一切「只在这台机器上成立」的东西（绝对路径、写死的端口、主驾桥的手工安装、只面向我们的文档）都算缺口。

## 1. 插件治理缺口

| ID | 现象 | 证据 | 影响 | 修法 | 状态 |
|---|---|---|---|---|---|
| PM-01 | 两个安装入口会打架：市场里的「安装」按钮执行 `dsh plugin --profile <当前 profile>`，在工作台里跑就是装进 bench，**绕过白名单与验证** | `dshmarket/lib/dsh-cli.js` 里 `spawnShim(file,[...args,'plugin','--profile',profile,...])` | 装上了但界面看不见（2026-10-27 实测过的现象） | `wb.py fix-ui`：扫描**已装**插件、补 `keepNav`、验证客户端入口是否真被页面加载。谁装的都能补齐治理 | **已完成（2026-10-27）**：`fix-ui` 实测认出 4 个插件 + dshmarket 的「插件市场」+ 页面加载状态 |
| PM-02 | 装前不打快照、装崩不自动回滚 | `cmd_install_plugin` 只验证，无 backup/restore | 一次装崩要人工 `plugins remove` + 恢复，耗时且易错 | 装前存三件套（profile `package.json` + `pnpm-lock.yaml` + `ui-config.json` + 台账），验证不过自动还原并重装 | **已完成（2026-10-27）**：`backups\pre-install-<时间>\`；端口没起/插件未登记链接 → 自动回滚 |
| PM-03 | 没有安全模式 | `wb.py start` 只能全量启动 | 插件把 webServer 搞挂 = 界面打不开，只能命令行救 | `wb.py start-safe`：按每个第三方插件的 `cordis.patch.yml` 抠出 entry id，生成**一次性** `state\safe-mode.patch.yml`（`--patch` 叠加，不写 profile），只禁用第三方、保留内置与自研三个 → 界面能开；退出用 `wb.py restart-safe` | **已完成（2026-10-27）**：实测禁用 `dsh-market` 后页面正常（标题/两个界面插件都在、market 缺席），`restart-safe` 后 market 回归 |
| PM-04 | `keepNav` 只增不删 | 原来只有 append | 卸载后白名单残留 | `ui-config.json` 里记 `navByPlugin`（哪个插件写的），`uninstall-plugin` 按插件清 | **已完成（2026-10-27）**：卸载实测清掉「测试分区」 |
| PM-05 | 装的是 `latest`，不锁版本；无安装台账 | profile 里写 `"latest"` | 复现/排障无法知道"当时装的是哪个版本" | 新装/升级时把**确切版本**写进 profile（优先注册表缓存，其次 npm，都没有才退 latest 并警告）；`state\installed.json` 记 包名/版本/来源/时间/客户端入口/槽位 | **已完成（2026-10-27）**：升级 dshmarket 后 profile 里是 `1.71.1`，面板 `source: dshmarket@1.71.1` |
| PM-06 | 没有装前兼容预判 | 只能运行期撞；`dshmarket` 声明 peer 最低 `0.2.1-alpha.3` 却在 `0.2.1-alpha.1` 上能跑 | 预判过严会误杀，过宽会撞崩 | `preflight` 里做**三档结论**：`compatible`（能完整跑）/ `degraded`（能跑但列明各项降级）/ `incompatible`（装不上，列阻断项）；`install` 门禁只在 incompatible 时中止 | **已完成（2026-10-27）**：alpha.1 与 rc.3 判 compatible；合成 harness 验出 degraded（缺 sessionController/reflect/settings.section → 3 条降级说明）与 incompatible（缺 webServer/sidebar.panellist，退出码 1）；`--json` 给界面用 |
| PM-07 | 无搜索、无更新检查 | 只能按确切包名装 | 市场里 7211 个插件只能靠外部翻 | `plugin-search <关键词>` 读注册表缓存；`plugin-update [<包名>] --apply` 对比并升级（复用装前快照/验证/回滚） | **已完成（2026-10-27）**：搜索命中 353 条按下载量排序带能力标记；`plugin-update` 从 `1.70.2 → 1.71.1` 真升级成功（升级前后 `--apply` 各踩一坑，见下） |
| PM-08 | 卸载不清 `node_modules` | pnpm 不剪（`dsh-wb-web` 那次是手动 `rmdir`） | 残留死链，`linked` 状态会骗人 | 卸载后删包目录 + 空的 scope 目录 | **已完成（2026-10-27）**：实测连 `@240xu` 空 scope 一起清 |
| PM-09 | 插件面板信息太薄 | 只有 名称 / 版本 / 是否登记 / 是否链接 + 备注 | 看不出「来源、声明能力、上次验证时间、可升级」 | 面板加列：来源、能力徽章（`credentials`/`fs-write` 这类标 ⚠，来自社区注册表）、上次验证、可升级版本 | **已完成（2026-10-27）**：`/wb-api/plugins` 合并「台账 + 注册表缓存」；面板实测显示 `来源 … · 能力 shell/dynamic-code/fs-write/… ⚠ · 上次验证 10-27 12:02 · 可升级 1.70.2→1.71.1` |
| PM-10 | **客户没法自助备份/还原**：安装器只有「回滚运行时」（那是 app 副本），没有备份/还原快照的入口 | `wb_gui.py` 原按钮表只有 install/rollback/start/stop… | 客户出问题时只能找我们 | 安装器加「立即备份…」「快照列表」「还原快照…」+ 还原后询问「安全重启」；`wb.py backups --json` 给界面机器可读出口；`wb.py restart-safe` 走维护模式重启 | **已完成（2026-10-27）**：GUI 截图确认按钮在位；备份→破坏→还原演练通过（css 哈希回到基线、被删插件文件恢复、运行时健康） |

## 2. 分发/移植缺口（客户独立安装到别的 harness）

| ID | 现象 | 证据 | 修法 | 状态 |
|---|---|---|---|---|
| DIST-01 | **主驾桥没有自动化安装**：`wb.py install` 里没有任何把 `dsh-workbench-bridge` 装进主 profile 的步骤 | `cmd_install` 无 bridge 相关代码 | `wb.py attach` / `detach`：只改目标 profile 的 `package.json`（依赖 + bundles），装软依赖桥，默认**只预览**，`--apply` 才写，写前备份清单；`detach` 反向清理含 `node_modules` 链接 | **已完成（2026-10-27）**：假 home 演练通过（装→幂等→卸→语义还原），真实主 profile 只做了预览（哈希未变） |
| DIST-02 | 端口写死：`59430` 出现 19 处；`config.json` 存绝对 install/home | `Select-String 59430` 计数 | 端口改成「`config.json` 的 `port` → `DSH_WORKBENCH_PORT` → 59430」，启动时若被别的程序占用就自动往上挑一个并写回 config；界面端口从 `/wb-ui/config` 读（品牌文字 + 水印 CSS 变量）；桥每次调用前读 config 解析端口（缓存 5 秒） | **已完成（2026-10-27）**：改 59431 实测监听/配置回报/`/wb-api` 全通，再改回 59430 |
| DIST-03 | `seeds\*` 里含本机绝对路径（`link:E:/DSH-WORKBENCH/...`） | `seeds\bench\package.json`、`seeds\main-profile\package.json` | 种子改 `${WB_ROOT}` / `${WB_HOME}` 占位，`ensure_profile` 建 profile 时渲染成真实路径 | **已完成（2026-10-27）**：渲染自检无残留占位符；`seeds\bench` 同时补齐三个自研插件（此前只有 api-browser） |
| DIST-04 | 文档全部面向"这台机器" | `docs\handoff.md` 里 12 处 `E:\DSH-WORKBENCH` | 新增面向客户/新机器的 `docs\install-for-customer.md` | **已完成（2026-10-27）**：分发包 docs 里有 `install-for-customer.md`（三步安装/验证/安装器按钮/FAQ）、`compat-matrix.md`（哪些版本能跑、怎么开测试床）、`interface-baseline.md`；另有 `README.md`（总览）与 `ui\README.md`（改界面指南）。内部记录（handoff/upgrade-policy/事故记录/prepublish 清单）按前缀排除，不进包 |
| DIST-05 | 没有分发物 | 无打包脚本、无版本号策略、无许可说明 | `wb.py pack` 输出 `dist\DSH-Workbench-<版本>\`（tools/ui/docs/seeds/plugins + `config.template.json` + `README.md` + `MANIFEST.json`），排除 `app/home/state/logs/backups/attic/ref`、内部文档与**测试插件（dshmarket）** | **已完成（2026-10-27）**：44 文件 / 4 插件 / **本机绝对路径 0 处**；MANIFEST 里有 `testOnlyPlugins` 显式声明 |

## 3. 明确的「不做」

- **收编市场 UI**：不做。它是测试插件、不保证长期存在；我们只做机制（`fix-ui`），不把它的界面当架构。
- **把市场里的安装按钮改造成我们的入口**：不做（同上）。用户从市场装了，事后 `wb.py fix-ui` 一键补齐即可。

## 4. 建议顺序

1. ~~`fix-ui`（PM-01）+ `uninstall-plugin`（PM-04/PM-08）~~ **已完成 2026-10-27**
2. ~~装前快照 + 失败回滚（PM-02）~~ **已完成 2026-10-27**（台账 PM-05 部分完成）
3. ~~`attach`/`detach`（DIST-01）~~ **已完成 2026-10-27**（预览/幂等/卸载/守卫均演练通过，真实主 profile 未动）
4. 端口/路径可移植（DIST-02/03）+ 客户文档（DIST-04）
5. 其余（PM-03/05 锁版本/06/07/09、DIST-05）

> 备注（2026-10-27）：做 1、2 时发现「重启抢端口」的真凶不是 `restart` 本身，而是**supervisor 看到端口空出来就抢先起实例**。所以维护型重启必须走「suspend → 等端口释放 → start → resume」（`wb.py` 里的 `safe_restart`），否则日志里永远有 EADDRINUSE 假故障。

## 5. 升级演练踩的两个坑（2026-10-27）

`plugin-update dshmarket --apply`（1.70.2 → 1.71.1）第一次、第二次都失败了，但**两次回滚都干净**（profile 回到 `latest`、实际版本仍是 1.70.2、工作台照常跑）。第三次成功。

1. **`name@version` 被当成依赖名**：`cmd_plugins add` 老逻辑把 `dshmarket@1.71.1` 整串写进 `dependencies` 的键 → pnpm 报 `ERR_PNPM_INVALID_DEPENDENCY_NAME`。修：新增 `split_npm_spec()` 拆「名字 / 版本」，并把版本当值写入（顺带实现锁定版本）。
2. **验证阶段用整串当插件名**：`normalize_pkg_name()` 对 `dshmarket@1.71.1` 原样返回 → 去 `node_modules/dshmarket@1.71.1` 找目录找不到 → 判失败并回滚。修：`normalize_pkg_name()` 也走 `split_npm_spec()`，只留包名。

教训：**升级路径和安装路径必须共用同一套"名字规范化"**，否则一个按裸名、一个按带版本号，就会互相拆台；而且这类错误会被"验证失败→自动回滚"掩盖成"升级就是不成功"，必须看日志里的 `找不到目录 / 清单里没有` 才能定位。

## 6. 空环境验收（2026-10-27 首轮）

做法：把 `dist\DSH-Workbench-*` 复制成「客户解压后的样子」（`state\client-sim\wb`），配一个**假 harness home**（只有 `profiles\desktop\package.json`），在本机以 `DSH_WORKBENCH_ROOT` 指向副本跑命令，**不碰真实配置**。

| 检查项 | 结果 |
|---|---|
| `paths --redetect --home <假> --install E:\SSS` | ✅ 写进**副本自己的** `config.json`，不污染本机 |
| `doctor`（副本视角） | ✅ 报出「未同步运行时 / profile 未建 / 看门狗未运行」——符合空环境预期 |
| `attach --apply --no-install` | ✅ 桥链接解析到**副本自己的** `plugins\dsh-workbench-bridge`（证明根目录推导可移植） |
| `detach --apply --no-install` | ✅ 假 profile 还原为 `deps:{}`、`bundles:[base,web-app]` |

**这一步抓出 3 个真 bug（已修）**：
1. `pnpm.mjs` 路径写死在本机 `E:\DSH\home\...` → 改成从检测到的 `MAIN_HOME` 推导，找不到只警告（只有装插件才需要）
2. `is_our_workbench()` 只要端口上有 `/wb-ui` 就认领 → 现在比对 `/wb-ui` 回报的 `uiDir` 是否等于自己的 `ui/`，避免把别人的工作台当成自己的（副本视角已验证会报「被别的程序占着」）
3. 记忆库路径写死 `E:\肥鱼工作区\.dsh-meow\memory.db` → 改成现查，缺了就显示「跳过」，不再报错
4. 附带：`java 缺失（需要时装到 G 盘）` 这种本机文案改成「未安装（可选）」

还没验的（下一步）：真正的 `install`（要复制 1.7GB 运行时到副本）与副本里启动/打开页面。

### 6.1 第二轮：真 install（2026-10-27，含 1.65GB 运行时复制）

做法同上，但这次让 `install` 真跑：复制 `E:\SSS` → `state\client-sim2\wb\app`（**10009 文件 / 1.65 GB / 约 9 秒**），并用 `DSH_WB_NO_SHORTCUTS=1` 防止动到桌面快捷方式与开机启动项。

| 检查项 | 结果 |
|---|---|
| 端口冲突自动避让 | ✅ 59430 被我方实例占着 → 自动改用 **59431** 并写进副本 config |
| 种子渲染 | ✅ 副本 profile 里的 `link:` 全部指向**副本自己的** `plugins\...` |
| 首次启动 | ⚠️ **服务起来了但三个插件全被跳过**（`dsh: skipping profile bundle … cannot resolve`），`/wb-ui` 404 |
| 自愈 | ✅ 新加的逻辑等待 25 秒 → 自动 `restart-safe` → 注入层就绪 |
| 页面 | ✅ 标题 `DSH 工作台`、`wb-ui-css/js` 已注入、`dsh-wb-api-browser` 与 `dsh-wb-sessions` 的 client 都在模块表；`dshmarket` 不在 |

**这一轮抓出的真 bug**：`install` 存在「服务先起、插件后解析」的时序问题，第一次启动会**静默跳过所有插件**（客户会看到"工作台=裸 harness"）。
修法（已落地）：①pnpm 之后逐个检查 `node_modules/<pkg>/package.json` 是否真的可读，缺了就再装一次；②启动后用 `wait_ui_ready()` 等 `/wb-ui` 应答（且 `uiDir` 必须是自己的），没就绪就**自动 restart-safe 一次**，仍失败则明确报错并提示看 `startup-*.log`。
另加 `DSH_WB_NO_SHORTCUTS=1`：演练/CI/批量部署时不动用户桌面与开机启动项。


## 7. 验收标准（怎么算做完）

- 装一个插件：一条命令，装前有快照，装后自动验证，失败自动回滚，台账里有记录
- 卸一个插件：一条命令，白名单/`node_modules`/台账三处都干净
- 从市场装的插件：跑一次 `fix-ui` 后界面就能看见（不需要人工改代码）
- 换一台机器：`install` → `attach` → 打开页面 → 三个自研插件与顶栏全部正常，全程不碰绝对路径
