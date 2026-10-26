// dsh-wb-sessions — 工作台的“会话视图”后端。
// 只做代理：读主驾的 state 文件拿到端口与 token，再转发到主驾桥 /wb-bridge/session*。
// 会话本体始终在主 harness，这里不落任何数据。
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

export const inject = []

const PREFIX = '/wb-sessions'
const WB_ROOT = process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH'
const STATE = join(WB_ROOT, 'state')
const started = new WeakSet()

function sendJson(res, status, body) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
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

    const main = await resolveMain()
    if (!main.port) {
      sendJson(res, 503, { ok: false, error: '找不到主 harness 端口（主驾没开？）' })
      return
    }
    const headers = { accept: 'application/json', 'x-wb-token': main.token }

    try {
      if (url.pathname === `${PREFIX}/list`) {
        const r = await fetch(`http://127.0.0.1:${main.port}/wb-bridge/sessions`, { headers, signal: AbortSignal.timeout(25000) })
        sendJson(res, r.status, await r.json())
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
      sendJson(res, 404, { ok: false, error: 'unknown endpoint' })
    } catch (error) {
      sendJson(res, 502, { ok: false, error: String(error?.message ?? error) })
    }
  }

  ctx.effect(() => server.register({ kind: 'prefix', path: PREFIX, handler }))
  ctx.logger?.info?.(`wb-sessions: ${PREFIX}/* ready`)
}
