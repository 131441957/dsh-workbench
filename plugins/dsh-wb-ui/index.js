// dsh-wb-ui — 工作台的 webui 注入层。
// 原理：webServer.tapIndex(html => html) 纯字符串改写，把 ui/workbench.css / workbench.js
// 塞进浏览器拿到的 index.html。**不修改安装目录里的任何文件**，删掉 ui 文件或停用本插件即恢复原样。
import { readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

export const inject = []

const WB_ROOT = process.env.DSH_WORKBENCH_ROOT || 'E:\\DSH-WORKBENCH'
const UI_DIR = join(WB_ROOT, 'ui')
const started = new WeakSet()
let applied = 0

function readUi(name) {
  try {
    return readFileSync(join(UI_DIR, name), 'utf8')
  } catch {
    return ''
  }
}

function fileInfo(name) {
  try {
    const p = join(UI_DIR, name)
    const st = statSync(p)
    return { exists: true, bytes: st.size, mtime: st.mtime.toISOString() }
  } catch {
    return { exists: false, bytes: 0, mtime: null }
  }
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
        try { apply(ctx) } catch (error) { ctx.logger?.warn?.(`wb-ui: retry failed: ${String(error)}`) }
        return
      }
      if (tries < 120) setTimeout(retry, 1000)
    }
    setTimeout(retry, 1000)
    return
  }

  const transform = (html) => {
    const css = readUi('workbench.css')
    const js = readUi('workbench.js')
    let out = html
    if (css) {
      const block = `<style id="wb-ui-css" data-wb="1">\n${css}\n</style>`
      out = /<\/head>/i.test(out) ? out.replace(/<\/head>/i, block + '\n</head>') : block + out
    }
    if (js) {
      const block = `<script id="wb-ui-js" data-wb="1">\n${js}\n</script>`
      out = /<\/body>/i.test(out) ? out.replace(/<\/body>/i, block + '\n</body>') : out + block
    }
    applied += 1
    return out
  }

  ctx.effect(() => server.tapIndex(transform))

  const handler = async (req, res) => {
    const url = new URL(req.url || '/', 'http://127.0.0.1')

    // 页面把真实 DOM 结构（标签/类名/位置/尺寸）POST 过来，落到 state\dom-snapshot.json，
    // 供改样式时按真实类名下手，不再靠猜。
    if (req.method === 'POST' && url.pathname === '/wb-ui/dom') {
      const chunks = []
      let total = 0
      try {
        for await (const chunk of req) {
          total += chunk.length
          if (total > 4 * 1024 * 1024) throw new Error('payload too large')
          chunks.push(chunk)
        }
        const text = Buffer.concat(chunks).toString('utf8')
        const out = join(WB_ROOT, 'state', 'dom-snapshot.json')
        writeFileSync(out, text, 'utf8')
        res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
        res.end(JSON.stringify({ ok: true, bytes: text.length, path: out }))
      } catch (error) {
        res.writeHead(400, { 'content-type': 'application/json; charset=utf-8' })
        res.end(JSON.stringify({ ok: false, error: String(error?.message ?? error) }))
      }
      return
    }

    const body = {
      ok: true,
      uiDir: UI_DIR,
      css: fileInfo('workbench.css'),
      js: fileInfo('workbench.js'),
      indexRenders: applied,
    }
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
    res.end(JSON.stringify(body))
  }
  ctx.effect(() => server.register({ kind: 'prefix', path: '/wb-ui', handler }))

  ctx.logger?.info?.('wb-ui: tapIndex 已注册（ui/workbench.css + ui/workbench.js）')
}
