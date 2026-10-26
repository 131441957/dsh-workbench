// tools/search-asar.mjs — 在 app.asar（未压缩，文件内容原样存放）里按 UTF-8 字节搜字符串
// 用法: node search-asar.mjs <asar文件> <要搜的字符串> [上下文字节数]
import { openSync, readSync, fstatSync, closeSync } from 'node:fs'

const [, , file, needle, ctxArg] = process.argv
if (!file || !needle) {
  console.error('usage: node search-asar.mjs <asar> <needle> [contextBytes]')
  process.exit(2)
}
const ctx = Number(ctxArg) || 400
const target = Buffer.from(needle, 'utf8')
const fd = openSync(file, 'r')
const size = fstatSync(fd).size
const CHUNK = 4 * 1024 * 1024
let pos = 0
let carry = Buffer.alloc(0)
let hits = 0

while (pos < size) {
  const buf = Buffer.alloc(Math.min(CHUNK, size - pos))
  readSync(fd, buf, 0, buf.length, pos)
  const block = Buffer.concat([carry, buf])
  let idx = block.indexOf(target)
  while (idx >= 0) {
    hits += 1
    const abs = pos - carry.length + idx
    const start = Math.max(0, idx - ctx)
    const end = Math.min(block.length, idx + target.length + ctx)
    const text = block.slice(start, end).toString('utf8').replace(/[^\x09\x0a\x0d\x20-\x7e\u4e00-\u9fff\u3000-\u303f]/g, ' ')
    console.log(`\n===== hit #${hits} @ byte ${abs} =====`)
    console.log(text)
    if (hits >= 4) { closeSync(fd); process.exit(0) }
    idx = block.indexOf(target, idx + 1)
  }
  carry = block.slice(Math.max(0, block.length - target.length * 2))
  pos += buf.length
}
closeSync(fd)
console.log(`\n共 ${hits} 处命中`)
process.exit(hits ? 0 : 1)
