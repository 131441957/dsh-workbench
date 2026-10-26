// tools/test-markdown.mjs — 离线验证会话面板的 Markdown 渲染器（假 React）
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const file = process.argv[2] || 'E:/DSH-WORKBENCH/plugins/dsh-wb-sessions/client.js'
const code = readFileSync(file, 'utf8')

let registration = null
const sandbox = {
  window: { __ModuleLoader__: { load: (reg) => { registration = reg } } },
}
vm.createContext(sandbox)
vm.runInContext(code, sandbox, { filename: 'client.js' })

if (!registration) {
  console.error('FAIL: 模块没有注册')
  process.exit(1)
}

const createElement = (type, props, ...children) => ({ type, props: props || {}, children })
const React = {
  createElement,
  useState: (v) => [typeof v === 'function' ? v() : v, () => {}],
  useEffect: () => {},
  useRef: (v) => ({ current: v }),
  useMemo: (fn) => fn(),
}
const module_ = registration.factory((spec) => (spec === 'react' ? React : undefined))
const render = module_.__test__ && module_.__test__.renderMarkdown
if (typeof render !== 'function') {
  console.error('FAIL: 没有导出 renderMarkdown')
  process.exit(1)
}

const sample = [
  '## 实测结果',
  '',
  '| 检查 | 结果 |',
  '|---|---|',
  '| 桥 token | 已生成 |',
  '| 端口 | 52640 |',
  '',
  '本段有 **粗体**、`行内代码` 和 [链接](https://example.com)。',
  '',
  '- 第一项',
  '- 第二项',
  '',
  '```js',
  'console.log(1)',
  '```',
  '',
  '> 引用一行',
  '',
  '---',
].join('\n')

const tree = render(sample)
const kinds = tree.map((n) => (typeof n === 'string' ? 'text' : n.type))
const expect = ['h2', 'table', 'p', 'ul', 'pre', 'div', 'hr']
const okOrder = expect.every((tag, i) => kinds[i] === tag)

const tableNode = tree.find((n) => n && n.type === 'table')
const tbody = tableNode ? tableNode.children[1] : null
const flat = (node) => {
  if (!node) return []
  return node.children.flat(Infinity).filter(Boolean)
}
const bodyRowCount = tbody ? flat(tbody).filter((c) => c && c.type === 'tr').length : 0
const preText = (() => {
  const pre = tree.find((n) => n && n.type === 'pre')
  return pre ? pre.children[0].children[0] : ''
})()

const pass = okOrder && bodyRowCount === 2 && preText.includes('console.log(1)')
console.log(JSON.stringify({ kinds, bodyRowCount, preText, pass }))
process.exit(pass ? 0 : 1)
