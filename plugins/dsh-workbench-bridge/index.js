// dsh-workbench-bridge — host half（挂在主 harness 上）.
// 干两件事：① 给主界面提供“工作台是否接入”的状态 ② 给 agent 提供 workbench_* 工具。
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

export const inject = ['webServer', 'tools']

const PREFIX = '/wb-bridge'
const WB_PORT = Number(process.env.DSH_WORKBENCH_PORT || 59430)
const WB_ROOT = process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH'

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
    const res = await fetch(`http://127.0.0.1:${WB_PORT}/wb-api/health`, {
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

async function statusPayload() {
  const [live, build, mainStatus, health] = await Promise.all([
    readState('api-live.json'),
    readState('api-build.json'),
    readState('main-status.json'),
    probe(),
  ])
  return {
    workbench: {
      port: WB_PORT,
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
  const server = ctx.get('webServer')
  const tools = ctx.get('tools')

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
      sendJson(res, 404, { error: 'unknown endpoint' })
    }
    ctx.effect(() => server.register({ kind: 'prefix', path: PREFIX, handler }))
    ctx.logger?.info?.(`wb-bridge: ${PREFIX}/status ready (workbench port ${WB_PORT})`)
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
            ? [{ type: 'text', text: `工作台已接入（${WB_PORT}）：DSH ${value.version ?? '?'} · 服务 ${value.services ?? '?'} · 槽位 ${value.slots ?? '?'}` }]
            : [{ type: 'text', text: `工作台未接入（${WB_PORT}）：${value.reason ?? '不可达'}` }],
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

    ctx.effect(() => tools.register(statusTool))
    ctx.effect(() => tools.register(apiTool))
    ctx.effect(() => tools.register(pluginsTool))
    ctx.logger?.info?.('wb-bridge: tools workbench_status / workbench_api / workbench_plugins ready')
  } else {
    ctx.logger?.warn?.('wb-bridge: tools service unavailable')
  }
}
