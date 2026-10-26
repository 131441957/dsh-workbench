// tools/asar-probe.mjs — 只读探测 asar 头部；readSync 必须读满
import { openSync, readSync, fstatSync, closeSync } from 'node:fs'

const file = process.argv[2]
if (!file) { console.error('usage: node asar-probe.mjs <app.asar>'); process.exit(2) }

function readFully(fd, length, position) {
  const buf = Buffer.alloc(length)
  let done = 0
  while (done < length) {
    const n = readSync(fd, buf, done, length - done, position + done)
    if (n <= 0) throw new Error(`短读：期望 ${length}，实得 ${done}`)
    done += n
  }
  return buf
}

const fd = openSync(file, 'r')
const size = fstatSync(fd).size
const head = readFully(fd, 16, 0)
const jsonLen = head.readUInt32LE(8)
const buf = readFully(fd, jsonLen, 16)
const header = JSON.parse(buf.toString('utf8'))
let files = 0
const walk = (node) => {
  for (const key of Object.keys(node.files || {})) {
    const meta = node.files[key]
    if (meta.files) walk(meta)
    else files += 1
  }
}
walk(header)
let dataStart = 16 + jsonLen
if (dataStart % 4 !== 0) dataStart += 4 - (dataStart % 4)
console.log(JSON.stringify({ size, jsonLen, files, dataStart, fits: dataStart <= size }))
closeSync(fd)
