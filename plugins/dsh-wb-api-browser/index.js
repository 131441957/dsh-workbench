// dsh-wb-api-browser — host half.
// 做两件事：①把工作台 state/ 里采集好的接口基线用 HTTP 暴露出来；②读写"插件备注"。
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

export const inject = ['webServer']

const PREFIX = '/wb-api'

function stateDir() {
  return join(process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH', 'state')
}

// ── 插件备注：用户自己写的"这插件干嘛的/为什么装"，落在 state\plugin-notes.json ──
function notesFile() {
  return join(stateDir(), 'plugin-notes.json')
}

async function readNotes() {
  try {
    const raw = JSON.parse(await readFile(notesFile(), 'utf8'))
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) return raw
  } catch {
    /* 没有就是空的 */
  }
  return {}
}

async function writeNotes(notes) {
  const dir = stateDir()
  await mkdir(dir, { recursive: true })
  const target = notesFile()
  const tmp = `${target}.tmp`
  await writeFile(tmp, JSON.stringify(notes, null, 1) + '\n', 'utf8')
  await rename(tmp, target) // 先写临时文件再改名，避免写一半断电留半个 JSON
}

async function readBody(req, limit = 32 * 1024) {
  const chunks = []
  let total = 0
  for await (const chunk of req) {
    total += chunk.length
    if (total > limit) throw new Error('请求体过大')
    chunks.push(chunk)
  }
  const text = Buffer.concat(chunks).toString('utf8')
  return text ? JSON.parse(text) : {}
}

async function readJson(name) {
  try {
    return JSON.parse(await readFile(join(stateDir(), name), 'utf8'))
  } catch {
    return null
  }
}

/** 工作台 profile 里的插件：登记(bundles) / 已链接(node_modules) / 版本。 */
async function collectPlugins() {
  const home = process.env.DSH_HOME || 'E:\\DSH-WORKBENCH\\home'
  const profileDir = join(home, 'profiles', 'bench')
  let pkg
  try {
    pkg = JSON.parse(await readFile(join(profileDir, 'package.json'), 'utf8'))
  } catch (error) {
    return { profileDir, error: `读不到 profile 清单：${String(error)}`, plugins: [] }
  }
  const deps = pkg.dependencies || {}
  const bundles = (pkg.dsh && pkg.dsh.profile && pkg.dsh.profile.bundles) || []
  const plugins = []
  for (const [name, spec] of Object.entries(deps)) {
    const dir = join(profileDir, 'node_modules', name)
    let version = null
    let linked = false
    try {
      const meta = JSON.parse(await readFile(join(dir, 'package.json'), 'utf8'))
      version = meta.version || null
      linked = true
    } catch {
      linked = false
    }
    plugins.push({ name, spec, linked, version, inBundles: bundles.includes(name) })
  }
  return { profileDir, bundles, plugins }
}

function sendJson(res, status, body) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

export function apply(ctx) {
  const server = ctx.get('webServer')
  if (!server) {
    ctx.logger?.warn?.('wb-api-browser: webServer service unavailable, endpoints not registered')
    return
  }

  const handler = async (req, res) => {
    let url
    try {
      url = new URL(req.url ?? '/', 'http://127.0.0.1')
    } catch {
      sendJson(res, 400, { error: 'bad request url' })
      return
    }
    if (url.pathname === `${PREFIX}/health`) {
      sendJson(res, 200, { ok: true, stateDir: stateDir(), pid: process.pid })
      return
    }
    if (url.pathname === `${PREFIX}/plugins`) {
      sendJson(res, 200, await collectPlugins())
      return
    }
    if (url.pathname === `${PREFIX}/notes`) {
      if (req.method === 'POST') {
        let body
        try {
          body = await readBody(req)
        } catch (error) {
          sendJson(res, 400, { ok: false, error: `坏请求体：${String(error && error.message ? error.message : error)}` })
          return
        }
        const name = String(body.name || '').trim()
        if (!name) {
          sendJson(res, 400, { ok: false, error: '缺少 name' })
          return
        }
        // 备注清空 = 删掉这一条
        const note = String(body.note || '').replace(/\r\n/g, '\n').trim().slice(0, 2000)
        const notes = await readNotes()
        if (note) notes[name] = note
        else delete notes[name]
        try {
          await writeNotes(notes)
        } catch (error) {
          sendJson(res, 500, { ok: false, error: `写备注失败：${String(error && error.message ? error.message : error)}` })
          return
        }
        sendJson(res, 200, { ok: true, notes })
        return
      }
      sendJson(res, 200, { ok: true, notes: await readNotes(), file: notesFile() })
      return
    }
    const routes = {
      [`${PREFIX}/live`]: 'api-live.json',
      [`${PREFIX}/build`]: 'api-build.json',
      [`${PREFIX}/status`]: 'main-status.json',
    }
    const file = routes[url.pathname]
    if (file) {
      const data = await readJson(file)
      if (data === null) sendJson(res, 503, { error: `${file} not found in ${stateDir()}` })
      else sendJson(res, 200, data)
      return
    }
    sendJson(res, 404, { error: 'unknown endpoint', path: url.pathname })
  }

  ctx.effect(() => server.register({ kind: 'prefix', path: PREFIX, handler }))
  ctx.logger?.info?.('wb-api-browser: /wb-api/* ready')
}
