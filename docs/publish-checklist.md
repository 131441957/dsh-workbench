# 公开前清单（publish checklist）

> 生成于 2026-10-27。**公开仓库前必须逐条过一遍**；`wb.py prepublish` 会自动检查其中的硬性项。
> 背景：这个仓库**只有工作台这一个项目**，所以不需要拆子项目，但必须把第三方内容摘干净。

## 一键自检

```powershell
python tools\wb.py prepublish
```

- 退出码 0 = 硬性项全过（可能还有提醒）
- 退出码 1 = 有硬性项没处理，**不能公开**

当前状态（2026-10-27 跑）：硬性项全过；3 条提醒未决（见下）。

---

## 1. 必须处理：`ref/` 里的第三方代码

`ref/` 里有两类**不属于本项目**的内容：

| 路径 | 是什么 | 风险 |
|---|---|---|
| `ref/dsh-bootlock-20261027/atomic-write-0.2.1-*.mjs` | 从官方 `app.asar` 反解出的 DSH 运行时源码 | 公开＝再分发 DeepSeek 的 bundle 代码 |
| `ref/meow-memory-0.31.1-src/` | meow-memory 插件 0.31.1 的 TS 源码 | 若不是你的项目，公开＝再分发别人的代码 |

**已经做的**：`git rm --cached ref` + `.gitignore` 收 `ref/`（HEAD 已不含，本地 22 个文件保留可用）。

**还没做的**：历史提交里仍有这 22 个文件。二选一：

**方案 A：重写历史摘掉（推荐，前提是确认这些不该公开）**

```powershell
# 先备份整个仓库（含 .git）到别处，再动手
pip install git-filter-repo
git filter-repo --path ref --invert-paths
git remote add origin https://github.com/131441957/dsh-workbench.git   # filter-repo 会移除 remote
git push --force -u origin master
```

**方案 B：确认授权后保留**——只有在你确实拥有这些代码的再分发权（例如 meow-memory 是你自己的项目、且官方 bundle 片段属于合理引用）时才选这条路；选它就在本文件里记一句授权说明。

## 2. 必须处理：许可协议

仓库现在**没有 LICENSE**。公开＝默认保留所有权利（别人不能合法使用）。

```powershell
# 若要 MIT：在仓库根目录建 LICENSE，内容用 MIT 模板，版权行写你自己
```

决定后把结论写进本文件，别只写在脑子里。

## 3. 建议处理：文档里的本机绝对路径

当前 23 处（`docs/handoff.md` 12、`upgrade-policy.md` 6、`tools-plan.md` 2 等）。
不影响安全，但公开后别人照着走会踩空。两种做法：

- 改成相对路径（`tools\wb.py`），或
- 在 `docs\handoff.md` 顶部加一句「本文是本机交接笔记，路径按 `E:\DSH-WORKBENCH` 写，换机器自行替换」

## 4. 公开动作本身

```powershell
# 最后一次自检 + 打包验证
python tools\wb.py prepublish
python tools\wb.py pack --force

# 推送（之前一直是私有）
git push -u origin master

# 改成公开（不可逆提醒：别人会立刻能看到全部历史）
gh repo edit 131441957/dsh-workbench --visibility public --accept-visibility-change-consequences
```

## 5. 公开后补一下

- README 末尾的「状态」改成「已公开」，写清支持范围
- 确认 `.gitignore` 仍挡住 `app/ home/ state/ logs/ backups/ dist/ config.json`（含本机路径）
- 记一笔：公开日期 + 当时的 commit

---

## 附：这份清单是怎么来的

用户 2026-10-27 原话：

> 「做个记录，在选择上传公开时提醒我要去掉这些，因为我的项目只有这个工作台」

所以：**提醒不是靠记性，是靠 `wb.py prepublish` 每次跑一遍**。
