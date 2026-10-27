// tools/test-markdown.mjs — 离线验证「Harness会话」面板的 Markdown 渲染器
//
// 保护什么：消息必须按 Markdown 渲染（标题/粗体/行内代码/代码块/列表/表格/引用/分隔线/链接），
// 不能退化成 pre-wrap 纯文本——用户曾截图对比主驾界面，指出"很混乱"。
//
// 怎么做到不用浏览器：用 node:vm 造一个沙箱，塞一个**假 window.__ModuleLoader__** 把插件
// client.js 的注册对象抓出来，再用**假 React**（createElement 只收集 type/props/children）跑渲染，
// 最后断言产出的节点序列（kinds 顺序、表格行数、代码块内容）。
//
// 跑法：node tools/test-markdown.mjs [client.js 路径]
// 失败意味着：渲染器坏了，或假 React 与真实 API 的差异变大了（先怀疑测试本身）。
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

// 默认路径指向本仓库的插件；换机器/换根目录时传参数覆盖
const file = process.argv[2] || 'E:/DSH-WORKBENCH/plugins/dsh-wb-sessions/client.js'
const code = readFileSync(file, 'utf8')

// 抓注册对象：插件 client.js 的入口就是 window.__ModuleLoader__.load({ id, factory })
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
