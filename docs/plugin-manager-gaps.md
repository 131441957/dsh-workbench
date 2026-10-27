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
| PM-01 | 两个安装入口会打架：市场里的「安装」按钮执行 `dsh plugin --profile <当前 profile>`，在工作台里跑就是装进 bench，**绕过白名单与验证** | `dshmarket/lib/dsh-cli.js` 里 `spawnShim(file,[...args,'plugin','--profile',profile,...])` | 装上了但界面看不见（2026-10-27 实测过的现象） | 既然市场不算依赖，改为提供 `wb.py fix-ui`：扫描**已装**插件、补 `keepNav`、验证客户端入口是否真被页面加载。谁装的都能补齐治理 | 待做 |
| PM-02 | 装前不打快照、装崩不自动回滚 | `cmd_install_plugin` 只验证，无 backup/restore | 一次装崩要人工 `plugins remove` + 恢复，耗时且易错 | `install-plugin` 装前存三件套（profile `package.json` + `pnpm-lock.yaml` + `state\ui-config.json`），验证失败自动还原并移除包 | 待做 |
| PM-03 | 没有安全模式 | `wb.py start` 只能全量启动 | 插件把 webServer 搞挂 = 界面打不开，只能命令行救 | `wb.py start --safe`：用一份临时补丁把非内置 bundle 全部 `disabled: true` 启动，界面能开即能在面板里禁用/卸载 | 待做 |
| PM-04 | `keepNav` 只增不删 | `wb.py` 里只有 append（`cfg["keepNav"] = keep`） | 卸载后白名单残留，越积越乱 | `uninstall-plugin` 时同步清理该插件写入的标题 | 待做 |
| PM-05 | 装的是 `latest`，不锁版本；无安装台账 | profile 里写 `"latest"`；无 `installed.json` | 复现/排障无法知道"当时装的是哪个版本" | profile 写确切版本；`state\installed.json` 记 包名/版本/来源(npm 或目录)/时间/声明能力/验证结果 | 待做 |
| PM-06 | 没有装前兼容预判 | 只能运行期撞；`dshmarket` 声明 peer 最低 `0.2.1-alpha.3` 却在 `0.2.1-alpha.1` 上能跑 | 预判过严会误杀，过宽会撞崩 | `plugin-info` 里做 semver 比对，输出三档：满足 / 不满足但**实测可跑** / 不满足且风险高；并把结论写进台账 | 部分（有侦察，无结论分级） |
| PM-07 | 无搜索、无更新检查 | 只能按确切包名装 | 市场里 7211 个插件只能靠外部翻 | `plugin-search <关键词>` 读 `https://awesome-dsh-plugin.com/plugins.json`；`plugin-update` 对比已装版本 | 待做 |
| PM-08 | 卸载不清 `node_modules` | pnpm 不剪（`dsh-wb-web` 那次是手动 `rmdir`） | 残留死链，`linked` 状态会骗人 | 卸载后按包名删 `home\profiles\bench\node_modules\<pkg>`（含 scope 目录清理） | 待做 |
| PM-09 | 插件面板信息太薄 | 只有 名称 / 版本 / 是否登记 / 是否链接 + 备注 | 看不出「来源、声明能力、上次验证时间、本次是否加载」 | 面板加列：来源、能力标签（如 `credentials`/`fs-write`，来自市场 json）、上次验证、加载状态 | 待做 |

## 2. 分发/移植缺口（客户独立安装到别的 harness）

| ID | 现象 | 证据 | 修法 | 状态 |
|---|---|---|---|---|
| DIST-01 | **主驾桥没有自动化安装**：`wb.py install` 里没有任何把 `dsh-workbench-bridge` 装进主 profile 的步骤 | `cmd_install` 无 bridge 相关代码 | 新增 `wb.py attach` / `detach`：把桥以软依赖装进目标 harness 的 profile（写 `dependencies` + `dsh.profile.bundles` + pnpm install），失败可回滚；`detach` 反向移除 | 待做 |
| DIST-02 | 端口写死：`59430` 出现 19 处；`config.json` 存绝对 install/home | `Select-String 59430` 计数 | 端口从 `config.json`/`DSH_WORKBENCH_PORT` 读取，占用时自动 +1 探测；所有 UI 文案里的 59430 改成运行时取 | 待做 |
| DIST-03 | `seeds\*` 里含本机绝对路径（`link:E:/DSH-WORKBENCH/...`） | `seeds\bench\package.json`、`seeds\main-profile\package.json` | 种子改为模板（`${WB_ROOT}` 占位），`install` 时渲染；这两个文件只作快照参考时要在 README 标明 | 待做 |
| DIST-04 | 文档全部面向"这台机器" | `docs\handoff.md` 里 12 处 `E:\DSH-WORKBENCH` | 新增面向客户/新机器的 `docs\install-for-customer.md`：前置条件、安装步骤、验证、卸载、常见故障 | 待做 |
| DIST-05 | 没有分发物 | 无打包脚本、无版本号策略、无许可说明 | 输出可分发目录/first-run 引导（`publish/` 或 zip），带版本号与 CHANGELOG | 待做 |

## 3. 明确的「不做」

- **收编市场 UI**：不做。它是测试插件、不保证长期存在；我们只做机制（`fix-ui`），不把它的界面当架构。
- **把市场里的安装按钮改造成我们的入口**：不做（同上）。用户从市场装了，事后 `wb.py fix-ui` 一键补齐即可。

## 4. 建议顺序

1. `fix-ui`（PM-01）+ `uninstall-plugin`（PM-04/PM-08）——把"装/卸之后没人管"补上
2. 装前快照 + 失败回滚（PM-02）
3. `attach/detach`（DIST-01）——这是"能给别人装"的第一道门
4. 端口/路径可移植（DIST-02/03）+ 客户文档（DIST-04）
5. 其余（PM-03/05/06/07/09、DIST-05）

## 5. 验收标准（怎么算做完）

- 装一个插件：一条命令，装前有快照，装后自动验证，失败自动回滚，台账里有记录
- 卸一个插件：一条命令，白名单/`node_modules`/台账三处都干净
- 从市场装的插件：跑一次 `fix-ui` 后界面就能看见（不需要人工改代码）
- 换一台机器：`install` → `attach` → 打开页面 → 三个自研插件与顶栏全部正常，全程不碰绝对路径
