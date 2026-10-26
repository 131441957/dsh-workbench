// dsh-wb-web — 工作台的“能力出口”。
// 把工作台进程里的 ctx.web（搜索/抓取）暴露成 HTTP 路由，供主驾侧的桥调用。
// 软依赖：服务用 ctx.get 取，取不到就等，绝不因为缺服务把工作台启动卡死。
export const inject = []

const PREFIX = '/wb-web'
const started = new WeakSet()

function sendJson(res, status, body) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

export function apply(ctx) {
  if (started.has(ctx)) return
  started.add(ctx)

  const server = ctx.get('webServer')
  const web = ctx.get('web')

  if (!server) {
    // webServer 还没挂上（或新版改名）：保持空闲并重试，不影响启动
    let tries = 0
    const retry = () => {
      tries += 1
      if (ctx.get('webServer')) {
        started.delete(ctx)
        try {
          apply(ctx)
        } catch (error) {
          ctx.logger?.warn?.(`wb-web: retry failed: ${String(error)}`)
        }
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
      sendJson(res, 400, { error: 'bad request url' })
      return
    }

    if (url.pathname === `${PREFIX}/health`) {
      sendJson(res, 200, {
        ok: true,
        hasWeb: Boolean(ctx.get('web')),
        hasServer: true,
        pid: process.pid,
      })
      return
    }

    if (url.pathname === `${PREFIX}/search`) {
      const service = ctx.get('web')
      if (!service) {
        sendJson(res, 503, { ok: false, error: 'ctx.web 不可用（工作台没有 web 服务）' })
        return
      }
      const query = (url.searchParams.get('q') ?? '').trim()
      if (!query) {
        sendJson(res, 400, { ok: false, error: '缺少参数 q' })
        return
      }
      const limitRaw = Number(url.searchParams.get('limit') ?? '5')
      const maxResults = Number.isFinite(limitRaw) ? Math.min(Math.max(Math.trunc(limitRaw), 1), 20) : 5
      try {
        const result = await service.search({ query, maxResults }, AbortSignal.timeout(30000))
        sendJson(res, 200, {
          ok: true,
          query,
          content: result.content ?? null,
          truncated: Boolean(result.truncated),
          sources: (result.sources ?? []).map((s) => ({
            url: s.url,
            title: s.title ?? null,
            snippet: s.snippet ?? null,
          })),
        })
      } catch (error) {
        sendJson(res, 502, {
          ok: false,
          query,
          error: String(error && error.message ? error.message : error),
          code: error && error.code ? String(error.code) : null,
        })
      }
      return
    }

    sendJson(res, 404, { error: 'unknown endpoint', path: url.pathname })
  }

  ctx.effect(() => server.register({ kind: 'prefix', path: PREFIX, handler }))
  ctx.logger?.info?.(`wb-web: ${PREFIX}/search ready（ctx.web ${web ? '已就绪' : '暂不可用'}）`)
}
