// tools/test-session-map.mjs — 用真实会话日志验证桥的消息映射（user / assistant 两种形状）
import { readFileSync } from 'node:fs'
import { zstdDecompressSync } from 'node:zlib'

const file = process.argv[2]
if (!file) {
  console.error('usage: node test-session-map.mjs <session.v4.jsonl.zstd>')
  process.exit(2)
}

// 与 dsh-workbench-bridge 的 sessionPage 保持同一套映射逻辑
function mapEvent(event) {
  if (!event) return null
  if (!['user/message', 'assistant/message', 'system/message'].includes(event.type)) return null
  const data = event.data ?? {}
  const message = data.message ?? data
  const blocks = Array.isArray(message.content) ? message.content : []
  const text = blocks
    .filter((b) => b && b.type === 'text' && typeof b.text === 'string')
    .map((b) => b.text)
    .join('\n')
    .trim()
  if (!text) return null
  return { seq: event.seq, type: event.type, role: message.role ?? (event.type === 'user/message' ? 'user' : null), text }
}

const raw = zstdDecompressSync(readFileSync(file)).toString('utf8')
const counts = { user: 0, assistant: 0, other: 0, dropped: 0 }
const samples = { user: null, assistant: null }

for (const line of raw.split('\n')) {
  if (!line.trim()) continue
  let rec
  try { rec = JSON.parse(line) } catch { continue }
  const event = rec.event ?? rec
  if (!['user/message', 'assistant/message', 'system/message'].includes(event.type)) continue
  const mapped = mapEvent(event)
  if (!mapped) { counts.dropped += 1; continue }
  if (mapped.role === 'user') { counts.user += 1; if (!samples.user) samples.user = mapped.text.slice(0, 60) }
  else if (mapped.role === 'assistant') { counts.assistant += 1; if (!samples.assistant) samples.assistant = mapped.text.slice(0, 60) }
  else counts.other += 1
}

console.log(JSON.stringify({ counts, samples }, null, 2))
const pass = counts.user > 0 && counts.assistant > 0
process.exit(pass ? 0 : 1)
