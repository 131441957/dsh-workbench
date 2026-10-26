// snapshot-db.cjs — consistent read-only snapshot of a meow-memory SQLite DB.
// Usage: node snapshot-db.cjs <source.db> <dest.db>
// Uses VACUUM INTO so the copy includes committed WAL content and is defragmented.
const { DatabaseSync } = require('node:sqlite')
const fs = require('node:fs')
const path = require('node:path')

const [, , src, dest] = process.argv
if (!src || !dest) {
  console.error('usage: node snapshot-db.cjs <source.db> <dest.db>')
  process.exit(2)
}
if (!fs.existsSync(src)) {
  console.error('source missing: ' + src)
  process.exit(3)
}
fs.mkdirSync(path.dirname(dest), { recursive: true })
for (const suffix of ['', '-wal', '-shm']) {
  const p = dest + suffix
  if (fs.existsSync(p)) fs.rmSync(p, { force: true })
}

const db = new DatabaseSync(src, { readOnly: true })
const escaped = dest.replace(/'/g, "''")
db.exec(`VACUUM INTO '${escaped}'`)

const levels = ['soul', 'user', 'project', 'fact', 'lesson', 'topic', 'rules']
const counts = {}
for (const level of levels) {
  try {
    counts[level] = db.prepare(`SELECT COUNT(*) AS n FROM ${level}`).get().n
  } catch {
    counts[level] = null
  }
}
db.close()

const check = new DatabaseSync(dest, { readOnly: true })
const mirror = {}
for (const level of levels) {
  try {
    mirror[level] = check.prepare(`SELECT COUNT(*) AS n FROM ${level}`).get().n
  } catch {
    mirror[level] = null
  }
}
const integrity = check.prepare('PRAGMA integrity_check').get()
check.close()

const ok = levels.every((l) => counts[l] === mirror[l])
console.log(JSON.stringify({
  source: src,
  dest,
  bytes: fs.statSync(dest).size,
  integrity: integrity ? Object.values(integrity)[0] : 'unknown',
  counts,
  copyCounts: mirror,
  match: ok,
}))
process.exit(ok ? 0 : 4)
