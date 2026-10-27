/* ══════════════════════════════════════════════════════════════════════════
 * dsh-wb-ui —— 工作台的 webui 注入层（宿主侧）
 * --------------------------------------------------------------------------
 * 干的唯一一件事：用 `webServer.tapIndex(html => html)` 纯字符串改写首页，
 * 把 `ui/workbench.css` 与 `ui/workbench.js` 塞进浏览器拿到的 index.html。
 * **不修改安装目录里的任何文件**；删掉 ui 文件或停用本插件 → 界面立刻恢复原版。
 *
 * ── 它暴露的三条路由（客户端 workbench.js 会用到前两条）─────────────────
 *   GET  /wb-ui          → 状态：uiDir / css 与 js 的字节数与 mtime / indexRenders 次数
 *                           （wb.py 的 is_our_workbench() 就是比对这里的 uiDir 来判断
 *                            "端口上这个进程是不是我们这一份"，多套工作台共存时必须准）
 *   GET  /wb-ui/config   → `{ keepNav, port, fingerprint, probeNeeded }`：设置页裁剪白名单 +
 *                           实际端口 + 「已装插件指纹 / 需不需要静默扫一次设置」。
 *                           （白名单由 wb.py install-plugin 写进 state\ui-config.json；
 *                            端口读 config.json，客户机上可能不是 59430；
 *                            指纹 = 台账 + profile 依赖的 name@version，见 installedFingerprint()）
 *   POST /wb-ui/config   → 页面回写自动发现的分区标题（`sections`）与"已扫描"指纹（`scanned`）
 *   POST /wb-ui/dom      → 客户端把 DOM 结构 / 整段 HTML 上报，落到 state\ 下
 *                           （boot-diag.json / dom-snapshot.json / settings.html，用于设计样式）
 *
 * ── 三条不变量 ───────────────────────────────────────────────────────────
 * ① **软依赖**：`export const inject = []` + `ctx.get('webServer')` 取不到就每秒重试。
 *    绝不能写 `inject: ['webServer']` —— 官方改服务名会让本 entry pending → startup failed。
 * ② **根目录从自身位置推导**，不写死：同一台机器可能有多套工作台（主套 / 测试床），
 *    写死会让测试床去服务主套的 ui（2026-10-27 实测踩过）。
 * ③ **标题也在这里改**：`<title>DSH 工作台</title>`。放 tapIndex 而不是靠前端 JS，
 *    是为了让分发包天然带着、客户一眼分清"工作台 vs harness"。
 *
 * ── 改完怎么验证 ─────────────────────────────────────────────────────────
 *   curl http://127.0.0.1:59430/wb-ui           → uiDir 必须是**这一份**的 ui 目录
 *   wb.py status / python tools\test-http.py     → 17 项里包含 /wb-ui 认领与页面注入检查
 * ══════════════════════════════════════════════════════════════════════════ */
import { readFileSync, renameSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const inject = []

// 自己的根目录：优先环境变量，其次从本文件位置推导（plugins/<name>/index.js → 上两级）。
// 别写死路径——同一台机器可以有多套工作台（主套 / rc.3 测试床），写死会让床去伺主机套的 ui。
const PLUGIN_DIR = fileURLToPath(new URL('.', import.meta.url))
const WB_ROOT = process.env.DSH_WORKBENCH_ROOT || join(PLUGIN_DIR, '..', '..')
const UI_DIR = join(WB_ROOT, 'ui')
const started = new WeakSet()   // 防止同一个 ctx 被 apply 两次（重试路径会重新调用 apply）
let applied = 0                 // tapIndex 被调用次数 = 首页被改写了几次（/wb-ui 里上报）

// 读 ui 文件；读不到就返回空串（此时页面照常出，只是没有注入——不抛错、不影响启动）
function readUi(name) {
  try {
    return readFileSync(join(UI_DIR, name), 'utf8')
  } catch {
    return ''
  }
}

// 文件指纹：/wb-ui 里上报，用来判断"改了 ui 文件但没生效"是不是缓存/路径问题
function fileInfo(name) {
  try {
    const p = join(UI_DIR, name)
    const st = statSync(p)
    return { exists: true, bytes: st.size, mtime: st.mtime.toISOString() }
  } catch {
    return { exists: false, bytes: 0, mtime: null }
  }
}

// 本实例服务的是哪个 home / profile：进程环境变量最可靠（wb.py 启动时一定设了），
// 取不到才退回 `<根目录>\home` + bench。绝不写死 E:\ 路径（同一台机器可能多套工作台）。
const HOME_DIR = process.env.DSH_HOME || join(WB_ROOT, 'home')
const PROFILE = process.env.DSH_PROFILE || 'bench'

// 已装插件指纹（name@version 排序拼接）。
// 干什么用：页面靠它判断"要不要静默扫一次设置分区"。只注册 `settings.section`、
// 不注册 `sidebar.panellist` 的插件，在设置弹层被打开之前没人知道它加了什么分区标题，
// 顶栏就没有它的配置入口 —— 用户装完会觉得"没配置界面"（2026-10-27 dsh-pet 就是这样）。
// 指纹=台账 + profile 依赖（两个都算，市场里装的插件未必在台账里）；底座包不算"新插件"。
function installedFingerprint() {
  const seen = new Map()
  try {
    const led = JSON.parse(readFileSync(join(WB_ROOT, 'state', 'installed.json'), 'utf8'))
    for (const name of Object.keys(led)) seen.set(name, String(led[name]?.version || '?'))
  } catch { /* 还没有台账：只靠 profile 依赖 */ }
  try {
    const prof = JSON.parse(readFileSync(join(HOME_DIR, 'profiles', PROFILE, 'package.json'), 'utf8'))
    const deps = prof?.dependencies || {}
    for (const name of Object.keys(deps)) {
      if (name.startsWith('@deepseek-ai/')) continue
      if (seen.has(name)) continue
      let ver = String(deps[name] || '?')
      // `link:` / `file:` 依赖的值是路径，不是版本；去 node_modules 里读真实版本，
      // 免得指纹随"根目录路径"变化（同一个插件在主套和测试床上应该算出同一份指纹）。
      if (/^(link|file):/i.test(ver)) {
        try {
          ver = String(JSON.parse(readFileSync(join(HOME_DIR, 'profiles', PROFILE, 'node_modules', name, 'package.json'), 'utf8')).version || 'linked')
        } catch { ver = 'linked' }
      }
      seen.set(name, ver)
    }
  } catch { /* profile 还没建 */ }
  return Array.from(seen.entries())
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([name, ver]) => `${name}@${ver}`)
    .join('|')
}

// 插件入口：拿 webServer → 挂 tapIndex（改写首页）+ 注册 /wb-ui 路由
export function apply(ctx) {
  if (started.has(ctx)) return
  started.add(ctx)

  // 软依赖：webServer 可能比本插件晚就绪（或被改名）。取不到就每秒重试，最多 120 次。
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

  // 首页改写：每次页面加载都会跑一遍（纯字符串替换，幂等，读文件失败就跳过注入）
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
      const cfgPath = join(WB_ROOT, 'state', 'ui-config.json')
      let cfg = {}
      try {
        cfg = JSON.parse(readFileSync(cfgPath, 'utf8'))
      } catch {
        cfg = {}
      }
      // POST = 页面把**自动发现**到的插件设置分区回写（客户端发现比服务端猜标题可靠：
      // dsh-pet 的分区标题 install-plugin 就没猜出来，页面上却看得到）。
      if (req.method === 'POST') {
        const chunks = []
        let total = 0
        try {
          for await (const chunk of req) {
            total += chunk.length
            if (total > 1024 * 1024) throw new Error('payload too large')
            chunks.push(chunk)
          }
        } catch { /* 读失败就当空报告 */ }
        const raw = Buffer.concat(chunks).toString('utf8')
        let incoming = []
        let parsed = {}
        try {
          parsed = JSON.parse(raw || '{}')
          incoming = Array.isArray(parsed.sections) ? parsed.sections : []
        } catch { incoming = []; parsed = {} }
        const clean = [...new Set(incoming.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim()))]
        // replace=true：整份替换（页面发现某分区已不存在时用来清掉死标题）；
        // 默认"只增不减"，避免页面在设置还没渲染全时误删插件分区。
        const repl = Boolean(parsed.replace)
        let keepNav = Array.isArray(cfg.keepNav) ? cfg.keepNav.slice() : []
        let added = 0
        if (repl) {
          keepNav = clean
        } else {
          for (const t of clean) {
            if (!keepNav.includes(t)) { keepNav.push(t); added += 1 }
          }
        }
        // scanned = 页面**扫过一遍设置**之后回报的已装插件指纹（见 installedFingerprint）。
        // 记下来的意义：下次打开页面指纹没变就不用再静默扫（一次插件变更只探一次）。
        const scanned = typeof parsed.scanned === 'string' ? parsed.scanned.slice(0, 4000) : ''
        const scannedChanged = Boolean(scanned) && scanned !== cfg.scanned
        // settingsUnreachable = 客户端实测结论："这个版本的设置入口点了不弹层"（如 0.2.1-rc.3）。
        // 为真时下次加载直接保留左栏，让用户自己点，不再生成打不开的顶栏按钮。
        const unreachableChanged = typeof parsed.settingsUnreachable === 'boolean'
          && parsed.settingsUnreachable !== Boolean(cfg.settingsUnreachable)
        if (repl || added || scannedChanged || unreachableChanged) {
          cfg.keepNav = keepNav
          if (scannedChanged) cfg.scanned = scanned
          if (unreachableChanged) cfg.settingsUnreachable = parsed.settingsUnreachable
          try {
            // 先写 .tmp 再 rename：半个 JSON 会让界面下次读配置直接崩溃
            const tmp = `${cfgPath}.tmp`
            writeFileSync(tmp, JSON.stringify(cfg, null, 2) + '\n', 'utf8')
            renameSync(tmp, cfgPath)
          } catch (error) {
            res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
            res.end(JSON.stringify({ ok: false, error: String(error?.message ?? error) }))
            return
          }
        }
        res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
        res.end(JSON.stringify({ ok: true, added, keepNav, scanned: cfg.scanned || '' }))
        return
      }
      let port = 59430
      try {
        const root = JSON.parse(readFileSync(join(WB_ROOT, 'config.json'), 'utf8'))
        if (Number.isInteger(root.port) && root.port > 0) port = root.port
      } catch { /* 用默认端口 */ }
      const keepNav = Array.isArray(cfg.keepNav) ? cfg.keepNav.filter((x) => typeof x === 'string') : []
      // fingerprint/probeNeeded：插件集合变了就让页面静默扫一次设置分区（不可见，
      // 用户只会看到"装完插件刷新一下，顶栏就多了它的配置按钮"）。
      const fingerprint = installedFingerprint()
      const scanned = typeof cfg.scanned === 'string' ? cfg.scanned : ''
      res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
      res.end(JSON.stringify({
        ok: true,
        keepNav,
        port,
        fingerprint,
        probeNeeded: Boolean(fingerprint) && fingerprint !== scanned,
        settingsUnreachable: Boolean(cfg.settingsUnreachable),
      }))
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
