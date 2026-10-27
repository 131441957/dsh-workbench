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
| PM-03 | 没有安全模式 | `wb.py start` 只能全量启动 | 插件把 webServer 搞挂 = 界面打不开，只能命令行救 | `wb.py start --safe`：临时补丁把非内置 bundle 全部 `disabled: true` 启动 | 待做 |
| PM-04 | `keepNav` 只增不删 | 原来只有 append | 卸载后白名单残留 | `ui-config.json` 里记 `navByPlugin`（哪个插件写的），`uninstall-plugin` 按插件清 | **已完成（2026-10-27）**：卸载实测清掉「测试分区」 |
| PM-05 | 装的是 `latest`，不锁版本；无安装台账 | profile 里写 `"latest"` | 复现/排障无法知道"当时装的是哪个版本" | `state\installed.json` 记 包名/版本/来源/时间/客户端入口/槽位 | 部分（台账已有并含实际版本；profile 仍写 `latest`，未锁死） |
| PM-06 | 没有装前兼容预判 | 只能运行期撞；`dshmarket` 声明 peer 最低 `0.2.1-alpha.3` 却在 `0.2.1-alpha.1` 上能跑 | 预判过严会误杀，过宽会撞崩 | `plugin-info` 里做 semver 比对，输出三档结论 | 部分（有侦察，无结论分级） |
| PM-07 | 无搜索、无更新检查 | 只能按确切包名装 | 市场里 7211 个插件只能靠外部翻 | `plugin-search <关键词>` 读 `awesome-dsh-plugin.com/plugins.json`；`plugin-update` 对比已装版本 | 待做 |
| PM-08 | 卸载不清 `node_modules` | pnpm 不剪（`dsh-wb-web` 那次是手动 `rmdir`） | 残留死链，`linked` 状态会骗人 | 卸载后删包目录 + 空的 scope 目录 | **已完成（2026-10-27）**：实测连 `@240xu` 空 scope 一起清 |
| PM-09 | 插件面板信息太薄 | 只有 名称 / 版本 / 是否登记 / 是否链接 + 备注 | 看不出「来源、声明能力、上次验证时间、本次是否加载」 | 面板加列：来源、能力标签（如 `credentials`/`fs-write`，来自市场 json）、上次验证、加载状态 | 待做 |
| PM-10 | **客户没法自助备份/还原**：安装器只有「回滚运行时」（那是 app 副本），没有备份/还原快照的入口 | `wb_gui.py` 原按钮表只有 install/rollback/start/stop… | 客户出问题时只能找我们 | 安装器加「立即备份…」「快照列表」「还原快照…」+ 还原后询问「安全重启」；`wb.py backups --json` 给界面机器可读出口；`wb.py restart-safe` 走维护模式重启 | **已完成（2026-10-27）**：GUI 截图确认按钮在位；备份→破坏→还原演练通过（css 哈希回到基线、被删插件文件恢复、运行时健康） |

## 2. 分发/移植缺口（客户独立安装到别的 harness）

| ID | 现象 | 证据 | 修法 | 状态 |
|---|---|---|---|---|
| DIST-01 | **主驾桥没有自动化安装**：`wb.py install` 里没有任何把 `dsh-workbench-bridge` 装进主 profile 的步骤 | `cmd_install` 无 bridge 相关代码 | `wb.py attach` / `detach`：只改目标 profile 的 `package.json`（依赖 + bundles），装软依赖桥，默认**只预览**，`--apply` 才写，写前备份清单；`detach` 反向清理含 `node_modules` 链接 | **已完成（2026-10-27）**：假 home 演练通过（装→幂等→卸→语义还原），真实主 profile 只做了预览（哈希未变） |
| DIST-02 | 端口写死：`59430` 出现 19 处；`config.json` 存绝对 install/home | `Select-String 59430` 计数 | 端口改成「`config.json` 的 `port` → `DSH_WORKBENCH_PORT` → 59430」，启动时若被别的程序占用就自动往上挑一个并写回 config；界面端口从 `/wb-ui/config` 读（品牌文字 + 水印 CSS 变量）；桥每次调用前读 config 解析端口（缓存 5 秒） | **已完成（2026-10-27）**：改 59431 实测监听/配置回报/`/wb-api` 全通，再改回 59430 |
| DIST-03 | `seeds\*` 里含本机绝对路径（`link:E:/DSH-WORKBENCH/...`） | `seeds\bench\package.json`、`seeds\main-profile\package.json` | 种子改 `${WB_ROOT}` / `${WB_HOME}` 占位，`ensure_profile` 建 profile 时渲染成真实路径 | **已完成（2026-10-27）**：渲染自检无残留占位符；`seeds\bench` 同时补齐三个自研插件（此前只有 api-browser） |
| DIST-04 | 文档全部面向"这台机器" | `docs\handoff.md` 里 12 处 `E:\DSH-WORKBENCH` | 新增面向客户/新机器的 `docs\install-for-customer.md` | 部分：分发包自带 `README.md`（三步安装）+ `ui\README.md`（改界面指南）；内部记录（handoff/upgrade-policy/事故记录）不进包 |
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

## 5. 验收标准（怎么算做完）

- 装一个插件：一条命令，装前有快照，装后自动验证，失败自动回滚，台账里有记录
- 卸一个插件：一条命令，白名单/`node_modules`/台账三处都干净
- 从市场装的插件：跑一次 `fix-ui` 后界面就能看见（不需要人工改代码）
- 换一台机器：`install` → `attach` → 打开页面 → 三个自研插件与顶栏全部正常，全程不碰绝对路径
