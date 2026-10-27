/* ══════════════════════════════════════════════════════════════════════════
 * dsh-workbench-bridge —— 主驾侧的接入层（host half，**唯一挂在主 harness 的插件**）
 * --------------------------------------------------------------------------
 * 它只干三件事：
 *   ① 告诉主驾「工作台接没接上」（状态）
 *   ② 给主驾的 agent 三个工具：workbench_status / workbench_api / workbench_plugins / workbench_call
 *   ③ 会话桥：列主驾会话、读某次对话的历史、往某个会话里投递消息
 *
 * ── 路由（PREFIX = /wb-bridge）────────────────────────────────────────────
 *   GET  /status        公开，只读：工作台可达性/延迟/pid、主驾会话概览
 *   GET  /plugins       公开，只读：bench profile 里装了什么
 *   GET  /capabilities  公开，只读：工作台各插件声明的能力清单（20s 缓存，?fresh=1 强制刷新）
 *   POST /call          **需 x-wb-token**：按名调用某个能力（工作台侧 /wb-api/*）
 *   GET  /sessions      **需 token**：主驾会话列表
 *   GET  /session/page  **需 token**：某会话的历史消息
 *   POST /session/prompt **需 token**：往某会话投递一条消息（queue / steer）
 *   GET  /events        **需 token**：SSE，每 3 秒一帧 tick（工作台侧转发给页面）
 *
 * ── 三条不变量 ───────────────────────────────────────────────────────────
 * ① **软依赖**（最重要）：`export const inject = []` + `ctx.get('webServer'/'tools')` 取不到就
 *    延后重试。绝不能写 `inject: ['webServer','tools']` —— 官方一旦改服务名，本 entry 会 pending，
 *    进而 `startup failed`，**把主驾一起打死**（违反"官方更新不牵连"这条需求）。
 * ② **只读主驾**：不改主 profile、不碰 E:\SSS 与 home 里的数据；写操作只发生在
 *    `<工作台根>\state\bridge-token.txt`（本插件自己的 token 文件）。
 * ③ **端口动态**：工作台端口从它的 config.json 读（缓存 5 秒），工作台换端口后不必重启主程序。
 *
 * ── 鉴权模型（改路由前先看这段）───────────────────────────────────────────
 *   `tokenOk(req)` 校验请求头 `x-wb-token`，token 是本进程启动时随机生成并写到
 *   `<工作台根>\state\bridge-token.txt`（工作台侧读同一个文件）。
 *   设计上 /status、/plugins、/capabilities 是**公开只读**；写与会话类路由必须带 token。
 *   写不了 token 文件时会把 token 置空 → 所有需要鉴权的路由自动 401（宁可不可用，也不裸奔）。
 *
 * ── 改完怎么验证 ─────────────────────────────────────────────────────────
 *   python tools\test-http.py --bridge   → 17 项：/status 带 token、无 token 仍可读、
 *                                          /call 与 /sessions 无 token 应 401、call(plugins) 有结果
 *   ⚠️ 改本文件（宿主代码）**必须重启主程序**才生效（ESM 模块缓存），改工作台侧不用。
 * ══════════════════════════════════════════════════════════════════════════ */
import { randomBytes } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

// 软依赖：服务用 ctx.get 取，取不到就稍后重试。
// 绝不能写成 inject: ['webServer','tools']——那样一旦官方改服务名，本 entry 会 pending，
// 进而 startup failed，把主驾一起打死（违反“官方更新不牵连”的要求）。
export const inject = []

const started = new WeakSet()

const PREFIX = '/wb-bridge'
// 工作台端口：优先读工作台的 config.json（客户机上可能不是 59430），其次环境变量，最后默认值。
// 每次都重新读（缓存 5 秒），这样工作台换端口后桥也能跟上，不必重启主程序。
let portCache = { at: 0, port: 0 }
function wbPort() {
  const now = Date.now()
  if (portCache.port && now - portCache.at < 5000) return portCache.port
  let port = 0
  try {
    const cfg = JSON.parse(readFileSync(join(WB_ROOT, 'config.json'), 'utf8'))
    if (Number.isInteger(cfg.port) && cfg.port > 0) port = cfg.port
  } catch { /* 读不到往下走 */ }
  if (!port) port = Number(process.env.DSH_WORKBENCH_PORT || 59430)
  portCache = { at: now, port }
  return port
}
// 工作台根目录：优先环境变量，其次从桥自己的位置推导（它永远是 <root>/plugins/dsh-workbench-bridge）。
// 这样客户机上装到任何目录都对，不必依赖写死路径。
const PLUGIN_DIR = fileURLToPath(new URL('.', import.meta.url))
const WB_ROOT = process.env.DSH_WORKBENCH_ROOT || join(PLUGIN_DIR, '..', '..')

function sendJson(res, status, body) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

async function readState(name) {
  try {
    return JSON.parse(await readFile(join(WB_ROOT, 'state', name), 'utf8'))
  } catch {
    return null
  }
}

async function probe() {
  const started = Date.now()
  try {
    const res = await fetch(`http://127.0.0.1:${wbPort()}/wb-api/health`, {
      signal: AbortSignal.timeout(2000),
    })
    if (!res.ok) return { reachable: false, reason: `HTTP ${res.status}` }
    const body = await res.json()
    return { reachable: true, latencyMs: Date.now() - started, ...body }
  } catch (error) {
    return { reachable: false, reason: String(error && error.message ? error.message : error) }
  }
}

/** 直接读工作台的 profile 清单：工作台挂了也能回答“装了哪些插件”。 */
async function readBenchPlugins() {
  const profileDir = join(WB_ROOT, 'home', 'profiles', 'bench')
  let pkg
  try {
    pkg = JSON.parse(await readFile(join(profileDir, 'package.json'), 'utf8'))
  } catch (error) {
    return { profileDir, error: `读不到 profile：${String(error)}`, plugins: [] }
  }
  const deps = pkg.dependencies || {}
  const bundles = (pkg.dsh && pkg.dsh.profile && pkg.dsh.profile.bundles) || []
  const plugins = []
  for (const [name, spec] of Object.entries(deps)) {
    let linked = false
    let version = null
    try {
      const meta = JSON.parse(await readFile(join(profileDir, 'node_modules', name, 'package.json'), 'utf8'))
      linked = true
      version = meta.version || null
    } catch {
      linked = false
    }
    plugins.push({ name, spec, linked, version, inBundles: bundles.includes(name) })
  }
  return { profileDir, bundles, plugins }
}

// ── 会话桥（主驾的会话：列 / 读历史 / 发消息）────────────────────────────
const TOKEN_FILE = join(WB_ROOT, 'state', 'bridge-token.txt')
let bridgeToken = ''

function loadToken() {
  try {
    bridgeToken = randomBytes(16).toString('hex')
    writeFileSync(TOKEN_FILE, bridgeToken, 'utf8')
    return true
  } catch (error) {
    // 写不了盘就没法让工作台带 token，安全起见把会话路由整体关掉
    bridgeToken = ''
    console.warn?.('wb-bridge: 无法写入 token 文件：' + String(error))
    return false
  }
}

function tokenOk(req) {
  return bridgeToken !== '' && String(req.headers['x-wb-token'] || '') === bridgeToken
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

async function sessionList(ctx) {
  const sc = ctx.get('sessionController')
  if (!sc) return { ok: false, error: 'sessionController 不可用' }
  const value = await sc.list({}, AbortSignal.timeout(20000))
  // 摘要里的 projections.values 带会话标题等派生信息；只透出标量，避免载荷膨胀
  const scalars = (values) => {
    const out = {}
    if (!values || typeof values !== 'object') return out
    for (const [key, raw] of Object.entries(values)) {
      if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') out[key] = raw
    }
    return out
  }
  return {
    ok: true,
    items: (value?.items ?? []).map((s) => ({
      sessionId: s.sessionId,
      updatedAt: s.updatedAt,
      running: Boolean(s.running),
      blank: Boolean(s.blank),
      cwd: s.cwd ?? null,
      origin: s.origin ?? null,
      parentSessionId: s.parentSessionId ?? null,
      agentAvailable: Boolean(s.agentAvailable),
      projections: s.projections
        ? { asOfSeq: s.projections.asOfSeq, values: scalars(s.projections.values) }
        : null,
    })),
  }
}

async function sessionPage(ctx, sessionId, maxMessages) {
  const sc = ctx.get('sessionController')
  if (!sc) return { ok: false, error: 'sessionController 不可用' }
  const inspection = await sc.inspect(sessionId, AbortSignal.timeout(20000))
  const events = inspection?.events ?? []
  const throughSeq = events.length ? events[events.length - 1].seq : 0
  const page = await sc.page({
    address: { kind: 'session', sessionId },
    throughSeq,
    maxMessages,
  }, AbortSignal.timeout(20000))
  const messages = []
  for (const record of page?.records ?? []) {
    const event = record?.event
    if (!event) continue
    if (!['user/message', 'assistant/message', 'system/message'].includes(event.type)) continue
    const data = event.data ?? {}
    // assistant/system 是 { message: { role, content } }，user 直接是 { role, content }（实测差异）
    const message = data.message ?? data
    const blocks = Array.isArray(message.content) ? message.content : []
    const text = blocks
      .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
      .map((block) => block.text)
      .join('\n')
      .trim()
    if (!text) continue
    messages.push({
      seq: event.seq,
      time: event.time,
      type: event.type,
      role: message.role ?? (event.type === 'user/message' ? 'user' : null),
      text: text.length > 4000 ? text.slice(0, 4000) + '…' : text,
    })
  }
  return { ok: true, sessionId, throughSeq, hasMore: Boolean(page?.hasMore), messages }
}

async function sessionPrompt(ctx, sessionId, text, mode) {
  const sc = ctx.get('sessionController')
  if (!sc) return { ok: false, error: 'sessionController 不可用' }
  const value = await sc.prompt({
    requestId: `wb-${Date.now()}-${randomBytes(4).toString('hex')}`,
    sessionId,
    mode: mode === 'steer' ? 'steer' : 'queue',
    content: [{ type: 'text', text }],
  }, AbortSignal.timeout(30000))
  return { ok: Boolean(value?.accepted), accepted: Boolean(value?.accepted) }
}

// ── 工作台能力「按名调用」──────────────────────────────────────────────
// 工作台的每个插件可以在自己 package.json 的 dsh.workbench.capabilities 里声明能力，
// 工作台宿主把它们汇总到 /wb-api/capabilities；这里按名字取出来，代理一次 HTTP。
let capCache = { at: 0, data: null }

async function workbenchCapabilities(force = false) {
  if (!force && capCache.data && Date.now() - capCache.at < 20000) return capCache.data
  try {
    const res = await fetch(`http://127.0.0.1:${wbPort()}/wb-api/capabilities`, { signal: AbortSignal.timeout(5000) })
    const body = await res.json()
    capCache = { at: Date.now(), data: body }
    return body
  } catch (error) {
    // 失败不缓存，下次还试
    return { capabilities: [], count: 0, error: `工作台不可达或未实现 /wb-api/capabilities：${String(error?.message ?? error)}` }
  }
}

async function callCapability(name, params) {
  const caps = await workbenchCapabilities()
  const list = caps.capabilities || []
  const cap = list.find((c) => c.name === name)
  if (!cap) {
    return { ok: false, capability: name, error: `没有这个能力：${name}`, available: list.map((c) => c.name) }
  }
  const p = params && typeof params === 'object' ? params : {}
  let url = `http://127.0.0.1:${wbPort()}${cap.route}`
  const init = { method: cap.method, headers: { accept: 'application/json' }, signal: AbortSignal.timeout(60000) }
  if (cap.method === 'GET') {
    const qs = new URLSearchParams()
    for (const key of cap.query || []) {
      const value = p[key]
      if (value !== undefined && value !== null && value !== '') qs.set(key, String(value))
    }
    const q = qs.toString()
    if (q) url += (url.includes('?') ? '&' : '?') + q
  } else {
    const body = {}
    for (const key of cap.body || []) if (p[key] !== undefined) body[key] = p[key]
    init.headers['content-type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  try {
    const res = await fetch(url, init)
    const text = await res.text()
    let parsed
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = { raw: text.slice(0, 4000) }
    }
    return { ok: res.ok, capability: name, status: res.status, result: parsed }
  } catch (error) {
    return { ok: false, capability: name, error: String(error?.message ?? error) }
  }
}

async function statusPayload() {
  const [live, build, mainStatus, health] = await Promise.all([
    readState('api-live.json'),
    readState('api-build.json'),
    readState('main-status.json'),
    probe(),
  ])
  return {
    workbench: {
      port: wbPort(),
      reachable: health.reachable,
      pid: health.pid ?? null,
      stateDir: health.stateDir ?? null,
      reason: health.reason ?? null,
      version: live?.version ?? null,
      services: live?.counts?.services ?? null,
      slots: live?.counts?.slots ?? null,
      profileRows: build?.totals?.rows ?? null,
      snapshotAt: mainStatus?.collectedAt ?? null,
    },
  }
}

export function apply(ctx) {
  if (started.has(ctx)) return
  started.add(ctx)

  const server = ctx.get('webServer')
  const tools = ctx.get('tools')

  if (!server && !tools) {
    // 服务还没挂载（或新版改名了）：保持“已激活但什么都不做”，1 秒后重试，最多 2 分钟
    let tries = 0
    const retry = () => {
      tries += 1
      if (ctx.get('webServer') || ctx.get('tools')) {
        started.delete(ctx)
        try {
          apply(ctx)
        } catch (error) {
          ctx.logger?.warn?.(`wb-bridge: retry failed: ${String(error)}`)
        }
        return
      }
      if (tries < 120) setTimeout(retry, 1000)
      else ctx.logger?.warn?.('wb-bridge: webServer/tools 一直不可用，桥保持空闲（不影响主驾启动）')
    }
    setTimeout(retry, 1000)
    return
  }

  if (server) {
    const handler = async (req, res) => {
      let url
      try {
        url = new URL(req.url ?? '/', 'http://127.0.0.1')
      } catch {
        sendJson(res, 400, { error: 'bad request url' })
        return
      }
      if (url.pathname === `${PREFIX}/status`) {
        sendJson(res, 200, await statusPayload())
        return
      }
      if (url.pathname === `${PREFIX}/plugins`) {
        sendJson(res, 200, await readBenchPlugins())
        return
      }
      // 能力清单（工作台插件自己声明的）+ 按名调用
      if (url.pathname === `${PREFIX}/capabilities`) {
        sendJson(res, 200, await workbenchCapabilities(url.searchParams.get('fresh') === '1'))
        return
      }
      if (url.pathname === `${PREFIX}/call`) {
        if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'POST only' }); return }
        if (!tokenOk(req)) { sendJson(res, 401, { ok: false, error: 'bad token' }); return }
        try {
          const body = await readBody(req)
          const name = String(body.name || '').trim()
          if (!name) { sendJson(res, 400, { ok: false, error: '需要 name' }); return }
          sendJson(res, 200, await callCapability(name, body.params))
        } catch (error) {
          sendJson(res, 500, { ok: false, error: String(error?.message ?? error) })
        }
        return
      }
      // 会话桥：写操作一律要 token（工作台启动时读 state\bridge-token.txt）
      if (url.pathname === `${PREFIX}/sessions`) {
        if (!tokenOk(req)) { sendJson(res, 401, { ok: false, error: 'bad token' }); return }
        try {
          sendJson(res, 200, await sessionList(ctx))
        } catch (error) {
          sendJson(res, 502, { ok: false, error: String(error?.message ?? error) })
        }
        return
      }
      if (url.pathname === `${PREFIX}/session/page`) {
        if (!tokenOk(req)) { sendJson(res, 401, { ok: false, error: 'bad token' }); return }
        const id = url.searchParams.get('id') ?? ''
        const maxMessages = Math.min(Math.max(Number(url.searchParams.get('max')) || 30, 1), 200)
        if (!id) { sendJson(res, 400, { ok: false, error: '缺少参数 id' }); return }
        try {
          sendJson(res, 200, await sessionPage(ctx, id, maxMessages))
        } catch (error) {
          sendJson(res, 502, { ok: false, error: String(error?.message ?? error) })
        }
        return
      }
      if (url.pathname === `${PREFIX}/session/prompt`) {
        if (req.method !== 'POST') { sendJson(res, 405, { ok: false, error: 'method not allowed' }); return }
        if (!tokenOk(req)) { sendJson(res, 401, { ok: false, error: 'bad token' }); return }
        try {
          const body = await readBody(req)
          const id = String(body.sessionId || '')
          const text = String(body.text || '').trim()
          const mode = body.mode === 'steer' ? 'steer' : 'queue'
          if (!id || !text) { sendJson(res, 400, { ok: false, error: '需要 sessionId 与 text' }); return }
          sendJson(res, 200, await sessionPrompt(ctx, id, text, mode))
        } catch (error) {
          sendJson(res, 502, { ok: false, error: String(error?.message ?? error) })
        }
        return
      }
      // 实时事件流（SSE）：工作台订阅它就能实时拿到主驾会话状态与工作台在线情况
      if (url.pathname === `${PREFIX}/events`) {
        if (!tokenOk(req)) { sendJson(res, 401, { ok: false, error: 'bad token' }); return }
        res.writeHead(200, {
          'content-type': 'text/event-stream; charset=utf-8',
          'cache-control': 'no-cache, no-transform',
          connection: 'keep-alive',
          'x-accel-buffering': 'no',
        })
        let alive = true
        req.on('close', () => { alive = false })
        const tick = async () => {
          if (!alive) return
          let payload
          try {
            const wb = await probe()
            const sc = ctx.get('sessionController')
            let sessions = null
            if (sc) {
              const value = await sc.list({}, AbortSignal.timeout(8000))
              const items = value?.items ?? []
              sessions = {
                count: items.length,
                running: items.filter((s) => s.running).length,
                latest: items.slice(0, 5).map((s) => ({ id: s.sessionId, running: Boolean(s.running), at: s.updatedAt })),
              }
            }
            payload = { at: Date.now(), workbench: wb, sessions }
          } catch (error) {
            payload = { at: Date.now(), error: String(error?.message ?? error) }
          }
          try {
            res.write(`event: tick\ndata: ${JSON.stringify(payload)}\n\n`)
          } catch {
            alive = false
            return
          }
          setTimeout(tick, 3000)
        }
        tick()
        return
      }

      sendJson(res, 404, { error: 'unknown endpoint' })
    }
    ctx.effect(() => server.register({ kind: 'prefix', path: PREFIX, handler }))
    if (loadToken()) {
      ctx.logger?.info?.(`wb-bridge: ${PREFIX}/* ready（会话桥已启用，token 在 state\\bridge-token.txt）`)
    } else {
      ctx.logger?.warn?.(`wb-bridge: ${PREFIX}/status 可用，但会话桥因缺 token 被禁用`)
    }
  } else {
    ctx.logger?.warn?.('wb-bridge: webServer service unavailable')
  }

  if (tools) {
    const statusTool = {
      name: 'workbench_status',
      description: '查看 DSH 工作台（插件宿主，端口 59430）是否接入：可达性、插件数量、接口数量、快照时间。',
      parameters: { type: 'object', additionalProperties: false, properties: {} },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          required: ['reachable'],
          properties: {
            reachable: { type: 'boolean' },
            port: { type: 'number' },
            version: { type: 'string' },
            services: { type: 'number' },
            slots: { type: 'number' },
            snapshotAt: { type: 'string' },
          },
        },
        render: (_args, value) =>
          value.reachable
            ? [{ type: 'text', text: `工作台已接入（${wbPort()}）：DSH ${value.version ?? '?'} · 服务 ${value.services ?? '?'} · 槽位 ${value.slots ?? '?'}` }]
            : [{ type: 'text', text: `工作台未接入（${wbPort()}）：${value.reason ?? '不可达'}` }],
      },
      async execute() {
        const s = (await statusPayload()).workbench
        // 只回非空字段：工具输出必须是 lossless JSON，undefined 会直接报错
        const out = { reachable: s.reachable, port: s.port }
        if (s.version) out.version = s.version
        if (typeof s.services === 'number') out.services = s.services
        if (typeof s.slots === 'number') out.slots = s.slots
        if (s.snapshotAt) out.snapshotAt = s.snapshotAt
        if (s.reason) out.reason = s.reason
        return out
      },
      presentCall() {
        return { card: 'generic', title: 'workbench_status', kind: 'read' }
      },
    }

    const apiTool = {
      name: 'workbench_api',
      description: '读取工作台的接口基线数据：kind=services 取宿主服务清单，kind=slots 取前端槽位清单，kind=build 取 profile 组装结果，kind=status 取主驾状态快照。可用 query 做过滤。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        required: ['kind'],
        properties: {
          kind: { type: 'string', enum: ['services', 'slots', 'build', 'status'] },
          query: { type: 'string' },
          limit: { type: 'number' },
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          required: ['kind', 'count', 'items'],
          properties: {
            kind: { type: 'string' },
            count: { type: 'number' },
            items: { type: 'array', items: { type: 'object', additionalProperties: true } },
          },
        },
        render: (_args, value) => [
          { type: 'text', text: `workbench_api ${value.kind}: ${value.count} 条` },
        ],
      },
      async execute(args) {
        const limit = Math.min(Math.max(Number(args.limit) || 20, 1), 100)
        const needle = String(args.query ?? '').trim().toLowerCase()
        let items = []
        if (args.kind === 'services') {
          const live = await readState('api-live.json')
          items = (live?.services ?? []).map((s) => ({ key: s.key, methodCount: s.methodCount, description: s.description }))
        } else if (args.kind === 'slots') {
          const live = await readState('api-live.json')
          items = (live?.slots ?? []).map((s) => ({ name: s.name, kind: s.kind, scope: s.scope, purpose: s.purpose }))
        } else if (args.kind === 'build') {
          const build = await readState('api-build.json')
          items = (build?.layers ?? []).map((l) => ({ layer: l.layer, rows: l.rows.length }))
        } else {
          const st = await readState('main-status.json')
          items = st ? [{ collectedAt: st.collectedAt, ports: st.mainHarness?.ports ?? [], memory: st.memory ?? {} }] : []
        }
        if (needle) {
          items = items.filter((it) => JSON.stringify(it).toLowerCase().includes(needle))
        }
        return { kind: args.kind, count: items.length, items: items.slice(0, limit) }
      },
      presentCall() {
        return { card: 'generic', title: 'workbench_api', kind: 'read' }
      },
    }

    const pluginsTool = {
      name: 'workbench_plugins',
      description: '列出工作台 profile 里登记/链接的插件（工作台挂了也能查，因为直接读磁盘清单）。',
      parameters: { type: 'object', additionalProperties: false, properties: {} },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          required: ['count', 'items'],
          properties: {
            count: { type: 'number' },
            items: { type: 'array', items: { type: 'object', additionalProperties: true } },
          },
        },
        render: (_args, value) => [
          { type: 'text', text: `工作台插件 ${value.count} 个\n` + value.items.map((p) => `· ${p.name}${p.version ? ' v' + p.version : ''}${p.inBundles ? '' : '（未登记）'}${p.linked ? '' : '（未链接）'}`).join('\n') },
        ],
      },
      async execute() {
        const data = await readBenchPlugins()
        return { count: (data.plugins || []).length, items: data.plugins || [] }
      },
      presentCall() {
        return { card: 'generic', title: 'workbench_plugins', kind: 'read' }
      },
    }

    // 按名调用工作台插件的能力（能力名由插件自己声明，主驾这边不硬编码）
    const callTool = {
      name: 'workbench_call',
      description:
        '按名字调用工作台插件声明的能力。先用 name="capabilities" 查有哪些能力（sessions_list / sessions_page / sessions_send / workspaces / plugins / notes / note_set …），再带 params 调用。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        required: ['name'],
        properties: {
          name: { type: 'string', description: '能力名；传 capabilities 可列出全部' },
          params: { type: 'object', additionalProperties: true, description: '能力参数（GET 走 query 字段，POST 走 body 字段）' },
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: true,
          required: ['ok'],
          properties: {
            ok: { type: 'boolean' },
            capability: { type: 'string' },
            status: { type: 'number' },
            result: { type: 'object' },
            error: { type: 'string' },
            available: { type: 'array', items: { type: 'string' } },
          },
        },
        render: (_args, value) => {
          if (!value.ok) {
            const extra = Array.isArray(value.available) && value.available.length ? `\n可用能力：${value.available.join(', ')}` : ''
            return [{ type: 'text', text: `工作台能力 ${value.capability ?? ''} 调用失败：${value.error ?? '未知错误'}${extra}` }]
          }
          return [{ type: 'text', text: `工作台能力 ${value.capability} 返回（HTTP ${value.status}）：\n${JSON.stringify(value.result).slice(0, 1200)}` }]
        },
      },
      async execute(args) {
        return await callCapability(String(args.name || '').trim(), args.params)
      },
      presentCall() {
        return { card: 'generic', title: 'workbench_call', kind: 'read' }
      },
    }

    ctx.effect(() => tools.register(statusTool))
    ctx.effect(() => tools.register(apiTool))
    ctx.effect(() => tools.register(pluginsTool))
    ctx.effect(() => tools.register(callTool))
    ctx.logger?.info?.('wb-bridge: tools workbench_status / workbench_api / workbench_plugins / workbench_call ready')
  } else {
    ctx.logger?.warn?.('wb-bridge: tools service unavailable')
  }
}
