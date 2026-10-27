// 工作台插件模板 · 宿主侧（index.js）
// 只做两件事：拿 webServer 注册自己的 HTTP 路由；不碰 agent、不碰主驾。
// 复制后要改：PLUGIN_NAME / PREFIX。
export const inject = []

const PLUGIN_NAME = 'wb-plugin-template'
const PREFIX = '/wb-template'

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
    // 软依赖：拿不到就等（别用 inject 硬依赖，否则会让整个实例 pending）
    let tries = 0
    const retry = () => {
      tries += 1
      if (ctx.get('webServer')) {
        try { apply(ctx) } catch (error) { ctx.logger?.warn?.(`${PLUGIN_NAME}: retry failed: ${String(error)}`) }
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
    if (url.pathname === `${PREFIX}/hello`) {
      sendJson(res, 200, { ok: true, plugin: PLUGIN_NAME, at: Date.now() })
      return
    }
    sendJson(res, 404, { ok: false, error: 'unknown endpoint' })
  }

  ctx.effect(() => server.register({ kind: 'prefix', path: PREFIX, handler }))
  ctx.logger?.info?.(`${PLUGIN_NAME}: ${PREFIX}/* ready`)
}
