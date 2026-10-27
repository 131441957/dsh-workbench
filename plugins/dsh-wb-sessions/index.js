// dsh-wb-sessions — 工作台的“会话视图”后端。
// 只做代理：读主驾的 state 文件拿到端口与 token，再转发到主驾桥 /wb-bridge/session*。
// 会话本体始终在主 harness，这里不落任何数据。
import { readFileSync, readdirSync, existsSync, createReadStream } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { createZstdDecompress } from 'node:zlib'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const inject = []

const PREFIX = '/wb-sessions'
// 自己的根目录：优先环境变量，其次从本文件位置推导（别写死，多套工作台共存时会串味）
const PLUGIN_DIR = fileURLToPath(new URL('.', import.meta.url))
const WB_ROOT = process.env.DSH_WORKBENCH_ROOT || join(PLUGIN_DIR, '..', '..')
const STATE = join(WB_ROOT, 'state')
const started = new WeakSet()

function sendJson(res, status, body) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

// ── 会话标题：主驾的 SessionSummary 没有 title，标题在会话日志的 session/title 事件里 ──
// 日志是多帧 zstd 追加写，必须流式解压（zstdDecompressSync 只解第一帧）；带 120 秒缓存。
const titleCache = new Map()

function dshHome() {
  // 工作台进程自己的 DSH_HOME 指向工作台的 home 目录，
  // 主驾的会话日志在 config.json 记录的 home 里，所以优先读 config.json。
  try {
    const cfg = JSON.parse(readFileSync(join(WB_ROOT, 'config.json'), 'utf8'))
    if (cfg.home) return cfg.home
  } catch { /* 忽略 */ }
  return process.env.DSH_HOME || 'E:\\DSH\\home'
}

// ── 主驾工作区注册表（只读，30 秒缓存）：路径 → 显示名 ────────────────
// 显示规则对齐原版 UI（从 app.asar 里查到的规则）：标题是 default-workspace 的工作区
// 按读者语言显示「默认工作区」，其余标题原样显示；没有标题时退回目录末段。
let wsCache = { at: 0, data: null }

function normalizeWsPath(value) {
  return String(value || '').replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()
}

function readWorkspaces() {
  if (wsCache.data && Date.now() - wsCache.at < 30000) return wsCache.data
  let data = { defaultWorkspaceId: '', workspaces: [] }
  try {
    const reg = JSON.parse(readFileSync(join(dshHome(), 'storages', 'workspace.json'), 'utf8'))
    const def = String((reg && reg.global && reg.global.defaultWorkspaceId) || '')
    const table = (reg && reg.tables && reg.tables.workspaces) || {}
    const workspaces = []
    for (const [id, ws] of Object.entries(table)) {
      const path = String((ws && ws.path) || '')
      const title = String((ws && ws.title) || '').trim()
      const tail = path.split(/[\\/]/).filter(Boolean).slice(-1)[0] || ''
      let label = title || tail
      if (label === 'default-workspace') label = '默认工作区'
      workspaces.push({
        id,
        path,
        key: normalizeWsPath(path),
        title,
        label: label || '未命名工作区',
        isDefault: id === def,
        sessionIds: Array.isArray(ws && ws.sessionIds) ? ws.sessionIds : [],
      })
    }
    data = { defaultWorkspaceId: def, workspaces }
  } catch {
    /* 注册表读不到就退回目录末段，不报错也不影响会话列表 */
  }
  wsCache = { at: Date.now(), data }
  return data
}

function findSessionLog(sessionId) {
  const root = join(dshHome(), 'sessions')
  const short = String(sessionId).replace(/^session-/, '')
  const dirName = 'session-' + short
  try {
    for (const ws of readdirSync(root, { withFileTypes: true })) {
      if (!ws.isDirectory()) continue
      const file = join(root, ws.name, dirName, 'session.v4.jsonl.zstd')
      if (existsSync(file)) return file
    }
  } catch { /* 忽略 */ }
  return ''
}

async function extractSessionTitle(file) {
  // 不用 pipeline：在 Cordis 里它会被取消作用域中止（"The operation was aborted"）。
  const chunks = []
  const decompressor = createZstdDecompress()
  decompressor.on('data', (chunk) => chunks.push(chunk))
  const finished = new Promise((resolve, reject) => {
    decompressor.on('end', resolve)
    decompressor.on('error', reject)
  })
  const source = createReadStream(file)
  source.on('error', (error) => decompressor.destroy(error))
  source.pipe(decompressor)
  await finished
  const raw = Buffer.concat(chunks).toString('utf8')
  let title = ''
  for (const line of raw.split('\n')) {
    if (!line.includes('"session/title"')) continue
    try {
      const rec = JSON.parse(line)
      if (rec.type === 'session/title' && rec.data && typeof rec.data.title === 'string') title = rec.data.title
    } catch { /* 跳过坏行 */ }
  }
  return { title, chars: raw.length }
}

async function readSessionTitle(sessionId) {
  const cached = titleCache.get(sessionId)
  const now = Date.now()
  if (cached && now - cached.at < 120000) return cached.title
  const file = findSessionLog(sessionId)
  if (!file) return cached ? cached.title : ''
  let title = ''
  try {
    const result = await extractSessionTitle(file)
    title = result.title
  } catch {
    title = cached ? cached.title : ''
  }
  if (!title && cached) title = cached.title
  titleCache.set(sessionId, { at: now, title })
  return title
}

async function readJson(name) {
  try {
    return JSON.parse(await readFile(join(STATE, name), 'utf8'))
  } catch {
    return null
  }
}

let cache = { port: 0, token: '', at: 0 }

async function resolveMain() {
  if (cache.port && cache.token && Date.now() - cache.at < 15000) return cache
  const status = await readJson('main-status.json')
  const ports = (status?.mainHarness?.ports ?? []).filter((p) => Number.isInteger(p) && p !== 59430)
  let token = ''
  try {
    token = (await readFile(join(STATE, 'bridge-token.txt'), 'utf8')).trim()
  } catch {
    token = ''
  }
  for (const port of ports) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/wb-bridge/status`, { signal: AbortSignal.timeout(2000) })
      if (res.ok) {
        cache = { port, token, at: Date.now() }
        return cache
      }
    } catch {
      /* 下一个端口 */
    }
  }
  return { port: 0, token, at: Date.now() }
}

async function readBody(req, limit = 64 * 1024) {
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

export function apply(ctx) {
  if (started.has(ctx)) return
  started.add(ctx)
  const server = ctx.get('webServer')
  if (!server) {
    let tries = 0
    const retry = () => {
      tries += 1
      if (ctx.get('webServer')) {
        started.delete(ctx)
        try { apply(ctx) } catch (error) { ctx.logger?.warn?.(`wb-sessions: retry failed: ${String(error)}`) }
        return
      }
      if (tries < 120) setTimeout(retry, 1000)
    }
    setTimeout(retry, 1000)
    return
  }

  const handler = async (req, res) => {
    let url
    try {
      url = new URL(req.url ?? '/', 'http://127.0.0.1')
    } catch {
      sendJson(res, 400, { ok: false, error: 'bad url' })
      return
    }

    if (url.pathname === `${PREFIX}/health`) {
      const main = await resolveMain()
      sendJson(res, 200, { ok: true, mainPort: main.port, hasToken: Boolean(main.token) })
      return
    }

    // 工作区注册表：面板「按工作区」分组拿显示名用（纯读主驾文件，不经过桥）
    if (url.pathname === `${PREFIX}/workspaces`) {
      const ws = readWorkspaces()
      sendJson(res, 200, { ok: true, ...ws })
      return
    }

    const main = await resolveMain()
    if (!main.port) {
      sendJson(res, 503, { ok: false, error: '找不到主 harness 端口（主驾没开？）' })
      return
    }
    const headers = { accept: 'application/json', 'x-wb-token': main.token }

    try {
      if (url.pathname === `${PREFIX}/title-debug`) {
        const id = url.searchParams.get('id') || ''
        const file = findSessionLog(id)
        const out = { id, home: dshHome(), file }
        if (file) {
          try {
            const result = await extractSessionTitle(file)
            out.title = result.title
            out.chars = result.chars
          } catch (error) {
            out.error = String(error && error.message ? error.message : error)
          }
        }
        sendJson(res, 200, out)
        return
      }

      if (url.pathname === `${PREFIX}/list`) {
        const r = await fetch(`http://127.0.0.1:${main.port}/wb-bridge/sessions`, { headers, signal: AbortSignal.timeout(25000) })
        const body = await r.json()
        // 主驾摘要没有标题，这里从会话日志补上（只读主驾文件，120 秒缓存）
        if (Array.isArray(body && body.items)) {
          for (const item of body.items) {
            // 优先用摘要投影里的标题（主驾已经算好了）；日志解析只作兜底
            const projected = item.projections && item.projections.values
              ? item.projections.values.title
              : ''
            let title = typeof projected === 'string' ? projected.trim() : ''
            if (!title) {
              try {
                title = (await readSessionTitle(item.sessionId)) || ''
              } catch {
                title = ''
              }
            }
            item.title = title
          }
        }
        sendJson(res, r.status, body)
        return
      }
      if (url.pathname === `${PREFIX}/page`) {
        const id = url.searchParams.get('id') ?? ''
        const max = url.searchParams.get('max') ?? '30'
        const r = await fetch(`http://127.0.0.1:${main.port}/wb-bridge/session/page?id=${encodeURIComponent(id)}&max=${encodeURIComponent(max)}`,
          { headers, signal: AbortSignal.timeout(25000) })
        const body = await r.json()
        // 系统提示词体积大又没信息量，界面上只留用户/助手消息
        if (Array.isArray(body?.messages)) {
          body.messages = body.messages.filter((m) => m.type === 'user/message' || m.type === 'assistant/message')
        }
        sendJson(res, r.status, body)
        return
      }
      if (url.pathname === `${PREFIX}/send`) {
        if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
        const body = await readBody(req)
        const r = await fetch(`http://127.0.0.1:${main.port}/wb-bridge/session/prompt`, {
          method: 'POST',
          headers: { ...headers, 'content-type': 'application/json' },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(35000),
        })
        sendJson(res, r.status, await r.json())
        return
      }
      if (url.pathname === `${PREFIX}/events`) {
        // 把主驾桥的 SSE 原样转发给浏览器（带 token）；客户端断开就中止上游请求
        const ac = new AbortController()
        req.on('close', () => ac.abort())
        let upstream
        try {
          upstream = await fetch(`http://127.0.0.1:${main.port}/wb-bridge/events`, { headers, signal: ac.signal })
        } catch (error) {
          sendJson(res, 502, { ok: false, error: String(error?.message ?? error) })
          return
        }
        if (!upstream.ok || !upstream.body) {
          sendJson(res, upstream.status || 502, { ok: false, error: '主驾桥事件流不可用' })
          return
        }
        res.writeHead(200, {
          'content-type': 'text/event-stream; charset=utf-8',
          'cache-control': 'no-cache, no-transform',
          connection: 'keep-alive',
          'x-accel-buffering': 'no',
        })
        const reader = upstream.body.getReader()
        try {
          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            if (value) res.write(Buffer.from(value))
          }
        } catch {
          /* 客户端断开或上游结束 */
        } finally {
          try { res.end() } catch { /* 已关闭 */ }
        }
        return
      }

      sendJson(res, 404, { ok: false, error: 'unknown endpoint' })
    } catch (error) {
      sendJson(res, 502, { ok: false, error: String(error?.message ?? error) })
    }
  }

  ctx.effect(() => server.register({ kind: 'prefix', path: PREFIX, handler }))
  ctx.logger?.info?.(`wb-sessions: ${PREFIX}/* ready`)
}
