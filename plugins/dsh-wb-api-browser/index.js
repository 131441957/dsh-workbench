// dsh-wb-api-browser — host half.
// 做两件事：①把工作台 state/ 里采集好的接口基线用 HTTP 暴露出来；②读写"插件备注"。
import { readFile, writeFile, rename, mkdir, readdir, stat } from 'node:fs/promises'
import { spawn } from 'node:child_process'
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

/** 工作台 profile 里的插件：登记(bundles) / 已链接(node_modules) / 版本 + 台账 + 注册表信息。 */
let registryCache = { at: 0, data: null }

async function loadRegistry() {
  if (registryCache.data && Date.now() - registryCache.at < 60000) return registryCache.data
  let data = { items: [] }
  try {
    data = JSON.parse(await readFile(join(stateDir(), 'registry.json'), 'utf8'))
  } catch {
    data = { items: [] }
  }
  if (!Array.isArray(data.items)) data.items = []
  registryCache = { at: Date.now(), data }
  return data
}

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
  // 台账（wb.py 写的安装记录）与注册表（社区插件清单，带声明能力）
  let ledger = {}
  try {
    ledger = JSON.parse(await readFile(join(stateDir(), 'installed.json'), 'utf8'))
  } catch {
    ledger = {}
  }
  const registry = await loadRegistry()
  const byNpm = new Map()
  for (const item of registry.items) {
    if (item && typeof item === 'object') {
      if (item.npm) byNpm.set(String(item.npm), item)
      if (item.name && !byNpm.has(String(item.name))) byNpm.set(String(item.name), item)
    }
  }

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
    const led = ledger[name] || {}
    const reg = byNpm.get(name) || null
    plugins.push({
      name,
      spec,
      linked,
      version,
      inBundles: bundles.includes(name),
      // 来源：台账里的 link:/npm 说明，没有就退回 profile 里的声明
      source: led.source || spec,
      installedAt: led.installedAt || null,
      lastVerifiedAt: led.lastFixAt || null,
      client: led.client || '',
      slots: Array.isArray(led.slots) ? led.slots : [],
      // 声明能力来自社区注册表（credentials/fs-write/network 这类要显眼）
      capabilities: reg && Array.isArray(reg.capabilities) ? reg.capabilities : null,
      latestVersion: reg ? reg.version || null : null,
      downloads: reg ? reg.downloads || null : null,
      inRegistry: Boolean(reg),
    })
  }
  return { profileDir, bundles, plugins, registryAt: registry.fetchedAt || null }
}

// ── 能力清单：各插件在自己 package.json 的 `dsh.workbench.capabilities` 里声明，
//    主驾桥读这里，按名字调用（这就是「工作台插件能被主 harness 调用」的通用通路）。
//    声明形状：{ name, description, method?('GET'|'POST'), route:'/wb-xxx/yyy', query?:['id'], body?:['text'] }
function pluginsRoot() {
  return join(process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH', 'plugins')
}

async function collectCapabilities() {
  let dirs = []
  try {
    dirs = await readdir(pluginsRoot())
  } catch (error) {
    return { capabilities: [], count: 0, error: `读不到 plugins 目录：${String(error && error.message ? error.message : error)}` }
  }
  const capabilities = []
  const skipped = []
  for (const dir of dirs.sort()) {
    let meta
    try {
      meta = JSON.parse(await readFile(join(pluginsRoot(), dir, 'package.json'), 'utf8'))
    } catch {
      continue
    }
    const declared = meta && meta.dsh && meta.dsh.workbench && meta.dsh.workbench.capabilities
    if (!Array.isArray(declared)) continue
    for (const c of declared) {
      if (!c || typeof c !== 'object') continue
      const name = String(c.name || '').trim()
      const route = String(c.route || '').trim()
      if (!name || !route.startsWith('/')) {
        skipped.push({ plugin: meta.name || dir, name: name || '(无名)', reason: '缺 name 或 route 不是绝对路径' })
        continue
      }
      capabilities.push({
        name,
        plugin: meta.name || dir,
        description: String(c.description || '').trim() || `${name}（${meta.name || dir}）`,
        method: String(c.method || 'GET').toUpperCase() === 'POST' ? 'POST' : 'GET',
        route,
        query: Array.isArray(c.query) ? c.query.map(String) : [],
        body: Array.isArray(c.body) ? c.body.map(String) : [],
      })
    }
  }
  capabilities.sort((a, b) => a.name.localeCompare(b.name))
  return { capabilities, count: capabilities.length, skipped, scannedAt: new Date().toISOString() }
}

// ── 实时服务列表：从反射层取，绝不触发 getter（避免实例化副作用）────────
// 结构（实测）：ctx.reflect.store 是 { Symbol(serviceName): { name, value, fiber, check } }
function serviceList(ctx) {
  const reflect = ctx.reflect || (ctx.root && ctx.root.reflect)
  const store = reflect && reflect.store
  if (!store || typeof store !== 'object') return null
  const out = []
  for (const sym of Object.getOwnPropertySymbols(store)) {
    const impl = store[sym]
    if (!impl) continue
    const key = String(sym).replace(/^Symbol\((.*)\)$/, '$1')
    if (!key || key === 'Symbol()') continue
    const methods = new Set()
    const collect = (target) => {
      if (!target || (typeof target !== 'object' && typeof target !== 'function')) return
      for (const name of Object.getOwnPropertyNames(target)) {
        if (name === 'constructor') continue
        const desc = Object.getOwnPropertyDescriptor(target, name)
        if (desc && typeof desc.value === 'function') methods.add(name)
      }
    }
    const value = impl.value
    collect(value)
    if (value && (typeof value === 'object' || typeof value === 'function')) {
      const proto = Object.getPrototypeOf(value)
      if (proto && proto !== Object.prototype) collect(proto)
    }
    out.push({ key, description: typeof impl.description === 'string' ? impl.description : '', methodCount: methods.size })
  }
  out.sort((a, b) => a.key.localeCompare(b.key))
  return out
}

// ── profile 分层：跑一次 dsh --dump-config 重算（只在点「刷新」时执行）──────
function cliPath() {
  const root = process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH'
  return join(root, 'app', 'resources', 'runtime', 'cli', 'bin', 'dsh.cmd')
}

function parseDumpConfig(stdout) {
  let layer = '?'
  const rows = Object.create(null)
  const order = []
  const ensure = (name) => {
    if (!rows[name]) {
      rows[name] = []
      order.push(name)
    }
  }
  for (const rawLine of String(stdout).split(/\r?\n/)) {
    const line = rawLine.trim()
    const m = /^#\s*==\s*(.+?)(?:,\s*patched by .*)?$/.exec(line)
    if (m) {
      layer = m[1].trim()
      ensure(layer)
      continue
    }
    const idm = /^-\s*id:\s*(\S+)/.exec(line)
    if (idm) {
      ensure(layer)
      rows[layer].push({ id: idm[1], name: '', disabled: false })
      continue
    }
    const namem = /^name:\s*'?([^']+)'?$/.exec(line)
    if (namem && rows[layer] && rows[layer].length) {
      rows[layer][rows[layer].length - 1].name = namem[1].trim()
      continue
    }
    if (line.startsWith('disabled:') && rows[layer] && rows[layer].length) {
      rows[layer][rows[layer].length - 1].disabled = line.toLowerCase().includes('true')
    }
  }
  const layers = order.map((name) => ({ layer: name, rows: rows[name] }))
  return {
    generatedAt: new Date().toISOString(),
    layers,
    totals: {
      layers: layers.length,
      rows: layers.reduce((sum, l) => sum + l.rows.length, 0),
      disabled: layers.reduce((sum, l) => sum + l.rows.filter((r) => r.disabled).length, 0),
    },
  }
}

// ── 面板用的合并快照：服务走实时枚举，槽位只能给静态快照（并标出采集时间）──
async function liveSnapshot(ctx) {
  const [snap, fileStat] = await Promise.all([
    readJson('api-live.json'),
    stat(join(stateDir(), 'api-live.json')).catch(() => null),
  ])
  const liveServices = serviceList(ctx)
  const services = liveServices || (snap && snap.services) || []
  const slots = (snap && snap.slots) || []
  const mtime = fileStat && fileStat.mtime ? fileStat.mtime.toISOString() : null
  return {
    collectedAt: new Date().toISOString(),
    version: (snap && snap.version) || 'unknown',
    services,
    servicesSource: liveServices ? 'live' : 'snapshot',
    servicesCollectedAt: liveServices ? new Date().toISOString() : mtime,
    slots,
    slotsSource: slots.length ? 'snapshot' : 'none',
    slotsCollectedAt: mtime,
    counts: { services: services.length, slots: slots.length },
  }
}

async function refreshBuild() {
  const cli = cliPath()
  const root = process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH'
  const home = process.env.DSH_HOME || join(root, 'home')
  const profile = process.env.DSH_PROFILE || 'bench'
  const stdout = await new Promise((resolve, reject) => {
    const child = spawn(process.env.ComSpec || 'cmd.exe', ['/c', cli, '--profile', profile, '--dump-config'], {
      env: { ...process.env, DSH_HOME: home, DSH_PROFILE: profile },
      windowsHide: true,
    })
    let out = ''
    let err = ''
    child.stdout.on('data', (chunk) => { out += chunk })
    child.stderr.on('data', (chunk) => { err += chunk })
    child.on('error', reject)
    child.on('close', (code) => {
      if (code === 0) resolve(out)
      else reject(new Error(`dump-config 退出码 ${code}：${String(err).slice(0, 400)}`))
    })
    setTimeout(() => { try { child.kill() } catch { /* 已退出 */ } }, 120000)
  })
  const build = parseDumpConfig(stdout)
  build.workbenchProfile = profile
  await mkdir(stateDir(), { recursive: true })
  await writeFile(join(stateDir(), 'api-build.json'), JSON.stringify(build, null, 2) + '\n', 'utf8')
  return build
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
    if (url.pathname === `${PREFIX}/capabilities`) {
      sendJson(res, 200, await collectCapabilities())
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
    // 服务实时枚举 + 槽位静态快照（各自带来源与采集时间）
    if (url.pathname === `${PREFIX}/live`) {
      sendJson(res, 200, await liveSnapshot(ctx))
      return
    }
    // 重算 profile 分层（跑一次 dsh --dump-config）
    if (url.pathname === `${PREFIX}/refresh`) {
      if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
      try {
        const build = await refreshBuild()
        sendJson(res, 200, { ok: true, generatedAt: build.generatedAt, totals: build.totals })
      } catch (error) {
        sendJson(res, 500, { ok: false, error: String(error && error.message ? error.message : error) })
      }
      return
    }
    const routes = {
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
