// tools/test-sessions-group.mjs — 离线验证「按工作区」分组（假 React）
// 回归点：组头必须是工作区名，绝不能是会话标题（曾按 sessionLabel 分组，每条会话自成一组建头全是标题）
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const file = process.argv[2] || 'E:/DSH-WORKBENCH/plugins/dsh-wb-sessions/client.js'
const code = readFileSync(file, 'utf8')

let registration = null
const sandbox = { window: { __ModuleLoader__: { load: (reg) => { registration = reg } } } }
vm.createContext(sandbox)
vm.runInContext(code, sandbox, { filename: 'client.js' })

if (!registration) {
  console.error('FAIL: 模块没有注册')
  process.exit(1)
}

const React = {
  createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
  useState: (v) => [typeof v === 'function' ? v() : v, () => {}],
  useEffect: () => {},
  useRef: (v) => ({ current: v }),
  useMemo: (fn) => fn(),
}
const module_ = registration.factory((spec) => (spec === 'react' ? React : undefined))
const t = module_.__test__ || {}
if (typeof t.buildGroups !== 'function') {
  console.error('FAIL: 没有导出 buildGroups')
  process.exit(1)
}

// 模拟主驾返回的三条会话：两个在肥鱼工作区，一个在默认工作区
const sessions = [
  { sessionId: 'session-aef5e748-71a5-4314-82d8-87077bfc091c', cwd: 'E:\\肥鱼工作区', title: '检查 docs handoff.md 文件', updatedAt: 1793026304151, running: true },
  { sessionId: 'session-9f2a5771-a845-47de-9f78-b43154658561', cwd: 'E:\\肥鱼工作区', title: 'DeepSeek harness 附属 Web 隔离方案', updatedAt: 1793025880406, running: false },
  { sessionId: 'session-9bc52866-ce9d-440f-be14-af8484a6998e', cwd: 'G:\\documents\\deepseek-harness\\default-workspace', title: '检查E盘可用插件', updatedAt: 1793019165474, running: false },
]

// 模拟 /wb-sessions/workspaces 的返回
const workspaces = [
  { path: 'E:\\肥鱼工作区', key: 'e:\\肥鱼工作区', label: '肥鱼工作区', isDefault: false },
  { path: 'G:\\documents\\deepseek-harness\\default-workspace', key: 'g:\\documents\\deepseek-harness\\default-workspace', label: '默认工作区', isDefault: true },
]
const wsByPath = new Map(workspaces.map((w) => [w.key, w]))

const wsGroups = t.buildGroups(sessions, 'workspace', '', wsByPath)
const labels = wsGroups.map((g) => g.label)
const sizes = wsGroups.map((g) => g.items.length)
const titles = sessions.map((s) => s.title)
const labelIsTitle = labels.some((l) => titles.includes(l))

const recent = t.buildGroups(sessions, 'recent', '', wsByPath)
const recentIds = recent[0].items.map((s) => s.sessionId)

const filtered = t.buildGroups(sessions, 'workspace', '隔离', wsByPath)
const filterLabels = filtered.map((g) => g.label + ':' + g.items.length)

const checks = {
  groupCount: wsGroups.length === 2,
  labelsOk: labels.includes('肥鱼工作区') && labels.includes('默认工作区'),
  sizesOk: sizes.includes(2) && sizes.includes(1),
  notTitle: !labelIsTitle,
  recentSingle: recent.length === 1 && recent[0].label === '全部会话',
  recentSorted: recentIds[0] === 'session-aef5e748-71a5-4314-82d8-87077bfc091c',
  filterByTitle: filtered.length === 1 && filtered[0].items.length === 1,
}

const pass = Object.values(checks).every(Boolean)
console.log(JSON.stringify({ labels, sizes, filterLabels, checks, pass }, null, 1))
process.exit(pass ? 0 : 1)
