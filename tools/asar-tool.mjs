// tools/asar-tool.mjs — 只读访问 Electron asar：列目录 / 按前缀导出
// 头部布局（实测）：[0..4)=4  [4..8)=headerSize  [8..12)=jsonLen  [12..16)=padding  [16..)=JSON
// 数据区起点 = 16 + jsonLen（按 4 字节对齐）
// 用法:
//   node asar-tool.mjs list  <app.asar> [过滤] [--limit N]
//   node asar-tool.mjs extract <app.asar> <输出目录> <前缀...>
import { openSync, readSync, fstatSync, closeSync, mkdirSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'

const [, , cmd, asarPath, ...rest] = process.argv
if (!cmd || !asarPath) {
  console.error('usage: list|extract <asar> ...')
  process.exit(2)
}

const fd = openSync(asarPath, 'r') // 只读
const head = Buffer.alloc(16)
readSync(fd, head, 0, 16, 0)
const headerSize = head.readUInt32LE(4)
const jsonLen = head.readUInt32LE(8)
const JSON_AT = 16
const headerBuf = Buffer.alloc(jsonLen)
readSync(fd, headerBuf, 0, jsonLen, JSON_AT)
const header = JSON.parse(headerBuf.toString('utf8'))
let dataStart = JSON_AT + jsonLen
if (dataStart % 4 !== 0) dataStart += 4 - (dataStart % 4)
const fileSize = fstatSync(fd).size

const entries = []
const walk = (node, prefix) => {
  for (const [name, meta] of Object.entries(node.files || {})) {
    const p = prefix ? `${prefix}/${name}` : name
    if (meta.files) walk(meta, p)
    else entries.push({ path: p, size: Number(meta.size || 0), offset: Number(meta.offset || 0), unpacked: Boolean(meta.unpacked) })
  }
}
walk(header, '')

if (cmd === 'list') {
  const filter = rest.find((a) => !a.startsWith('--'))
  const li = rest.indexOf('--limit')
  const limit = li >= 0 ? Number(rest[li + 1]) : 25
  const hit = entries.filter((e) => !filter || e.path.includes(filter))
  console.log(`总文件 ${entries.length} | 命中 ${hit.length} | dataStart ${dataStart} (文件 ${fileSize})`)
  for (const e of hit.slice(0, limit)) console.log(`  ${String(e.size).padStart(8)}  ${e.path}`)
  process.exit(0)
}

if (cmd === 'extract') {
  const outDir = rest[0]
  const prefixes = rest.slice(1)
  if (!prefixes.length) { console.error('需要路径前缀'); process.exit(2) }
  let count = 0
  let bytes = 0
  for (const e of entries) {
    if (!prefixes.some((p) => e.path.startsWith(p))) continue
    if (e.unpacked || e.size === 0) continue
    const out = join(outDir, e.path)
    if (existsSync(out)) continue
    const at = dataStart + e.offset
    if (at + e.size > fileSize) { console.warn(`skip ${e.path}`); continue }
    const buf = Buffer.alloc(e.size)
    readSync(fd, buf, 0, e.size, at)
    mkdirSync(dirname(out), { recursive: true })
    writeFileSync(out, buf)
    count += 1
    bytes += e.size
  }
  console.log(`导出 ${count} 个文件 / ${(bytes / 1024 / 1024).toFixed(1)} MB → ${outDir}`)
  process.exit(0)
}

console.error('未知命令')
process.exit(2)
