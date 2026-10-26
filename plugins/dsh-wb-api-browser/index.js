// dsh-wb-api-browser — host half.
// 只做一件事：把工作台 state/ 里已经采集好的接口基线用 HTTP 暴露出来，供前端面板读。
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

export const inject = ['webServer']

const PREFIX = '/wb-api'

function stateDir() {
  return join(process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH', 'state')
}

async function readJson(name) {
  try {
    return JSON.parse(await readFile(join(stateDir(), name), 'utf8'))
  } catch {
    return null
  }
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
