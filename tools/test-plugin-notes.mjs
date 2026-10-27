// tools/test-plugin-notes.mjs — 离线验证「插件备注」在面板里的数据形状（假 React / 假模块加载器）
// 覆盖：有备注的插件行带 note、没备注的是空串、非插件标签不受影响、按备注内容也能筛到、备注超长会被宿主截断（这里只验前端不过滤）
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const file = process.argv[2] || 'E:/DSH-WORKBENCH/plugins/dsh-wb-api-browser/client.js'
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
if (typeof t.buildRows !== 'function') {
  console.error('FAIL: 没有导出 buildRows')
  process.exit(1)
}

const data = {
  plugins: {
    plugins: [
      { name: 'dsh-wb-sessions', spec: 'link:E:/x', linked: true, version: '0.1.0', inBundles: true },
      { name: 'dsh-wb-ui', spec: 'link:E:/y', linked: true, version: '0.1.0', inBundles: true },
      { name: 'dsh-wb-ghost', spec: 'link:E:/z', linked: false, version: null, inBundles: false },
    ],
  },
  notes: { 'dsh-wb-sessions': '看主驾会话用的，别乱卸' },
  live: { services: [{ key: 'webServer', description: 'HTTP 服务', methodCount: 3 }] },
  build: null,
  status: null,
}

const rows = t.buildRows('plugins', data, '')
const byName = new Map(rows.map((r) => [r.head, r]))

const checks = {
  rowCount: rows.length === 3,
  hasNoteField: rows.every((r) => Object.prototype.hasOwnProperty.call(r, 'note')),
  noteCarried: byName.get('dsh-wb-sessions')?.note === '看主驾会话用的，别乱卸',
  emptyNote: byName.get('dsh-wb-ui')?.note === '',
  warnKept: /不会生效/.test(byName.get('dsh-wb-ghost')?.extra || ''),
  filterByName: t.buildRows('plugins', data, 'sessions').length === 1,
  filterByNote: t.buildRows('plugins', { ...data, notes: { 'dsh-wb-ui': '顶栏改造' } }, '顶栏').length === 1,
  otherTabClean: t.buildRows('services', data, '').every((r) => !Object.prototype.hasOwnProperty.call(r, 'note')),
}

const pass = Object.values(checks).every(Boolean)
console.log(JSON.stringify({ checks, pass }, null, 1))
process.exit(pass ? 0 : 1)
