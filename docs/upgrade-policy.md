# 主驾升级了，工作台怎么办

## 一句话

工作台是 `E:\DSH-WORKBENCH\app` 里的**独立一整套**，主驾升级（`update-dsh.ps1` 换 `E:\SSS`）**不会碰它**。
代价是：主驾升级后，工作台会**停在旧版本**——这是设计，不是故障。

## 三种情况，三条命令

### 1）什么都不做（默认）
主驾升到新版，工作台继续用旧接口。旧插件照跑。
**风险点**：如果插件源码被改成只用新接口，旧版工作台会加载失败。用 `wb.py compat` 看版本，再 `wb.py start` 试一次就知道。

### 2）工作台跟随升级
```powershell
python E:\DSH-WORKBENCH\tools\wb.py sync-app --force
python E:\DSH-WORKBENCH\tools\wb.py api
python E:\DSH-WORKBENCH\tools\wb.py compat
```
- `sync-app --force`：先把旧 `app\` **改名**为 `backups\app-<旧版本>-<时间>`（秒级、不复制），再复制新版，完事自动重启工作台
- `api`：重新采集活体接口基线，对比服务/槽位增减
- `compat`：确认两边版本与插件 peer 约束

### 3）新版有问题，回滚
```powershell
python E:\DSH-WORKBENCH\tools\wb.py rollback
```
把当前 `app\` 另存，再把 `backups\` 里最近一份换回来，自动重启。

## 磁盘账

每跟一次新版，就会多留一份旧安装（1.69GB / 10009 文件）。建议只保留最近 1–2 份，多余的手动删：
```powershell
Get-ChildItem E:\DSH-WORKBENCH\backups -Directory | Sort-Object LastWriteTime | Select-Object -Skip 2 | Remove-Item -Recurse
```

## 版本不一致时怎么看

| 主驾 | 工作台 | 含义 |
|---|---|---|
| 新 | 旧 | 接口可能新增；旧插件通常仍可用（只要没被改成依赖新接口） |
| 旧 | 新 | 插件可能用了新版才有的接口 → 在主驾里加载会报错 |
| 一致 | 一致 | 接口行为应当相同（**当前就是这一种**） |

## 长期建议

给自己写的插件补上 `peerDependencies` 的 dsh 版本范围（目前只有 `meow-memory` 声明了 `@deepseek-ai/schemastery@^3.18.1`），
这样 `wb.py compat` 就能自动判断「这个插件能不能挂到这个版本上」，而不是靠人肉验证。

## 实测记录（2026-10-26，DSH 0.2.1-alpha.1）

- `sync-app --force`：旧 app 改名备份 → 复制 10009 文件 / 1691MB（4 秒）→ 自动重启成功
- `rollback`：当前 app 另存 → 换回备份 → 自动重启成功，版本仍 0.2.1-alpha.1
- 备份是**改名**完成的，不产生额外复制开销（同一磁盘）；额外占用来自新版那份复制
