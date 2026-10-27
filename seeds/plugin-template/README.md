# 工作台插件模板（复制即用）

工作台的核心约定：**装插件不需要改工作台的任何代码**。
顶栏（`ui\workbench.js`）会动态扫描应用侧栏里的入口行（`*_panelRow`），
插件只要注册了 `sidebar.panellist` + `main` 两处槽位，就会自己出现在顶栏上。

## 三步装一个插件

```powershell
# 1) 复制模板改名（目录名随意，包名必须是唯一的）
Copy-Item E:\DSH-WORKBENCH\seeds\plugin-template E:\DSH-WORKBENCH\plugins\dsh-wb-demo -Recurse

# 2) 改三处名字：package.json 的 name、cordis.patch.yml 的 name、client.js 的 id / LABEL / KEY
#    （宿主侧顺手改 PLUGIN_NAME / PREFIX）

# 3) 装进 bench profile 并重启
python E:\DSH-WORKBENCH\tools\wb.py plugins add E:\DSH-WORKBENCH\plugins\dsh-wb-demo
python E:\DSH-WORKBENCH\tools\wb.py restart
```

卸载：

```powershell
python E:\DSH-WORKBENCH\tools\wb.py plugins remove dsh-wb-demo
python E:\DSH-WORKBENCH\tools\wb.py restart
```

## 顶栏排序规则（`ui\workbench.js`）

- `LEFT_ORDER = ['Harness会话', '插件']`：左边的固定顺序
- `RIGHT_ORDER = ['状态', '设置']`：右边，顺序即显示顺序
- **不在上面两个列表里的入口，自动排到左边末尾** —— 所以新插件不用登记就能现身
- 想让某个新面板固定位置，把它的显示名加进 `LEFT_ORDER` / `RIGHT_ORDER`（这一步是可选的美化，不是必需的）

## 注意

- 宿主侧不要写 `export const inject = ['webServer']`（硬依赖会拖垮整个实例），用 `ctx.get('webServer')` + 重试。
- 客户端面板根节点加 `data-wb-panel`：顶栏遮罩靠它判断「我们的面板已就位」。
- 能力清单（`wb.py caps`）会自动扫 `plugins\*\package.json`，可选声明 `dsh.workbench.capabilities`。
