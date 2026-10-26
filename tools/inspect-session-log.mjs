// tools/inspect-session-log.mjs — 读会话 zstd 日志，统计事件类型，找用户消息的真实形状
import { readFileSync } from 'node:fs'
import { zstdDecompressSync } from 'node:zlib'

const file = process.argv[2]
if (!file) {
  console.error('usage: node inspect-session-log.mjs <session.v4.jsonl.zstd> [needle]')
  process.exit(2)
}
const needle = process.argv[3] || ''

const raw = zstdDecompressSync(readFileSync(file)).toString('utf8')
const lines = raw.split('\n').filter((l) => l.trim())

const typeCount = new Map()
const samples = new Map()
let hits = []

for (const line of lines) {
  let rec
  try {
    rec = JSON.parse(line)
  } catch {
    continue
  }
  const event = rec.event ?? rec
  const type = String(event.type ?? rec.type ?? 'unknown')
  typeCount.set(type, (typeCount.get(type) ?? 0) + 1)
  if (!samples.has(type)) samples.set(type, JSON.stringify(event).slice(0, 400))
  if (needle && line.includes(needle)) hits.push(line)
}

console.log('总行数', lines.length)
console.log('事件类型分布：')
for (const [type, count] of [...typeCount.entries()].sort((a, b) => b[1] - a[1])) {
  console.log(`  ${type.padEnd(28)} ${count}`)
}
if (needle) {
  console.log(`\n包含 "${needle}" 的记录数：${hits.length}`)
  for (const h of hits.slice(0, 3)) {
    const rec = JSON.parse(h)
    console.log('  ' + JSON.stringify(rec).slice(0, 900))
  }
}
