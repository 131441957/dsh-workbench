// dsh-wb-ui — 工作台的 webui 注入层。
// 原理：webServer.tapIndex(html => html) 纯字符串改写，把 ui/workbench.css / workbench.js
// 塞进浏览器拿到的 index.html。**不修改安装目录里的任何文件**，删掉 ui 文件或停用本插件即恢复原样。
import { readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const inject = []

// 自己的根目录：优先环境变量，其次从本文件位置推导（plugins/<name>/index.js → 上两级）。
// 别写死路径——同一台机器可以有多套工作台（主套 / rc.3 测试床），写死会让床去伺主机套的 ui。
const PLUGIN_DIR = fileURLToPath(new URL('.', import.meta.url))
const WB_ROOT = process.env.DSH_WORKBENCH_ROOT || join(PLUGIN_DIR, '..', '..')
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
    // 标签页标题：让浏览器/任务栏显示「DSH 工作台」而不是 harness 的名字。
    // 这条必须在这里做（tapIndex），这样分发包里也带着，客户一眼能分清工作台和 harness。
    out = /<title>[^<]*<\/title>/i.test(out)
      ? out.replace(/<title>[^<]*<\/title>/i, '<title>DSH 工作台</title>')
      : out.replace(/<head([^>]*)>/i, '<head$1><title>DSH 工作台</title>')
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
        let parsed = null
        try { parsed = JSON.parse(text) } catch { parsed = null }
        if (parsed && parsed.kind === 'html' && typeof parsed.html === 'string') {
          // 整段 HTML 导出（用来按真实类名裁剪设置页）
          const htmlOut = join(WB_ROOT, 'state', parsed.name || 'dump.html')
          writeFileSync(htmlOut, parsed.html, 'utf8')
          res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
          res.end(JSON.stringify({ ok: true, bytes: parsed.html.length, path: htmlOut }))
          return
        }
        writeFileSync(out, text, 'utf8')
        res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
        res.end(JSON.stringify({ ok: true, bytes: text.length, path: out }))
      } catch (error) {
        res.writeHead(400, { 'content-type': 'application/json; charset=utf-8' })
        res.end(JSON.stringify({ ok: false, error: String(error?.message ?? error) }))
      }
      return
    }

    // 界面裁剪的白名单 + 端口：装插件时由 wb.py install-plugin 自动写入 state\ui-config.json；
    // 端口来自 config.json（客户机上 59430 可能被占，工作台会换端口）
    if (url.pathname === '/wb-ui/config') {
      let cfg = {}
      try {
        cfg = JSON.parse(readFileSync(join(WB_ROOT, 'state', 'ui-config.json'), 'utf8'))
      } catch {
        cfg = {}
      }
      let port = 59430
      try {
        const root = JSON.parse(readFileSync(join(WB_ROOT, 'config.json'), 'utf8'))
        if (Number.isInteger(root.port) && root.port > 0) port = root.port
      } catch { /* 用默认端口 */ }
      const keepNav = Array.isArray(cfg.keepNav) ? cfg.keepNav.filter((x) => typeof x === 'string') : []
      res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
      res.end(JSON.stringify({ ok: true, keepNav, port }))
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
