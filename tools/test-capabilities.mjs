// tools/test-capabilities.mjs — 静态校验「按名调用」的能力声明
// 目的：声明了的能力必须真能调到——route 必须落在本插件 index.js 注册的前缀之下，
// 名字不能重复，method 只能是 GET/POST，参数白名单必须是数组。
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const root = process.argv[2] || 'E:/DSH-WORKBENCH/plugins'
const problems = []
const seen = new Map()
const caps = []

for (const dir of readdirSync(root).sort()) {
  const pkgPath = join(root, dir, 'package.json')
  if (!existsSync(pkgPath)) continue
  let meta
  try {
    meta = JSON.parse(readFileSync(pkgPath, 'utf8'))
  } catch (error) {
    problems.push(`${dir}: package.json 解析失败（${error.message}）`)
    continue
  }
  const declared = (((meta.dsh || {}).workbench || {}).capabilities) || []
  if (!Array.isArray(declared) || declared.length === 0) continue

  const indexPath = join(root, dir, 'index.js')
  const indexText = existsSync(indexPath) ? readFileSync(indexPath, 'utf8') : ''
  const prefixMatch = /const\s+PREFIX\s*=\s*['"`]([^'"`]+)['"`]/.exec(indexText)
  const prefix = prefixMatch ? prefixMatch[1] : null

  for (const c of declared) {
    const name = String((c && c.name) || '')
    const route = String((c && c.route) || '')
    const method = String((c && c.method) || 'GET').toUpperCase()
    if (!name) problems.push(`${dir}: 有声明缺 name`)
    if (seen.has(name)) problems.push(`能力名重复：${name}（${seen.get(name)} 与 ${dir}）`)
    seen.set(name, dir)
    if (!route.startsWith('/')) problems.push(`${name}: route 必须是绝对路径，实际 ${route}`)
    if (!prefix) problems.push(`${dir}: index.js 里找不到 const PREFIX，无法校验 route`)
    else if (route !== prefix && !route.startsWith(prefix + '/')) problems.push(`${name}: route ${route} 不在本插件前缀 ${prefix} 之下`)
    if (!['GET', 'POST'].includes(method)) problems.push(`${name}: method 只能是 GET/POST，实际 ${method}`)
    if (c.query !== undefined && !Array.isArray(c.query)) problems.push(`${name}: query 必须是数组`)
    if (c.body !== undefined && !Array.isArray(c.body)) problems.push(`${name}: body 必须是数组`)
    caps.push({ name, plugin: meta.name || dir, method, route })
  }
}

const pass = problems.length === 0
console.log(JSON.stringify({ count: caps.length, caps, problems, pass }, null, 1))
process.exit(pass ? 0 : 1)
