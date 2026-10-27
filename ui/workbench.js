/* ══════════════════════════════════════════════════════════════════════════
 * 工作台 UI 注入脚本（ui\workbench.js）
 * --------------------------------------------------------------------------
 * 谁注入它：plugins\dsh-wb-ui 在服务端用 webServer.tapIndex 把本文件塞进首页 </body> 前。
 * 改完刷新页面即生效；删掉本文件（或停用 dsh-wb-ui）→ 界面立刻恢复原版。
 * 不修改安装目录里任何文件，也不 fork 前端源码。
 *
 * ── 它到底做什么 ─────────────────────────────────────────────────────────
 * 原版界面是「左侧竖栏导航 + 中列内容」。工作台把导航改成顶部横向条：
 *   1. 把原侧栏那条链路（若干"窄而高"的容器）整体 display:none
 *   2. 另建一条 #wb-topbar；顶栏按钮点击时**去点原侧栏里的同名入口**
 *      （DOM click 对 display:none 的元素同样有效，所以不用重写任何面板逻辑）
 *   3. 面板清单**动态发现**（扫 `*_panelRow`），装/卸插件不用改本文件
 *
 * ── 三条不变量（改这个文件前务必守住）───────────────────────────────────
 * ① 一切类名匹配**只按后缀**：DSH 前端是 CSS-in-JS，类名 = 每版本重新生成的 hash 前缀
 *    + 稳定语义后缀。实测 alpha.1 = `OSewFq_frame`，rc.3 = `mP3x-q_frame`；
 *    写死前缀会**静默失效**（不报错，只是布局/裁剪悄悄不生效）。统一走 bySuffix()。
 * ② 判断"元素可见/文本"用 textContent，**不要用 innerText**：遮罩用 visibility:hidden
 *    藏主区，被藏元素没有 innerText（曾因此点击永不触发、面板挂不上）。
 * ③ 隐藏清单里不要放自己会用到的文字，并且 sweep 遍历时跳过 `#wb-topbar`
 *    （HIDE_TEXTS 曾经把顶栏自己新加的「插件」按钮一起藏了）。
 *
 * ── 文件结构（按出现顺序）────────────────────────────────────────────────
 *   [A] 状态与自诊断      state / __WB_UI__ / 错误捕获 / bootDiag() → state\boot-diag.json
 *   [B] 基础样式注入      attachStyle()：顶栏与 .wb-hidden 的样式
 *   [C] 弹窗与 toast      dismiss() 关「预览版说明」；sweep() 里静音无 agent 的报错 toast
 *   [D] 入口发现          scanSidebarEntries() / planTabs() / entryFor() / findButton()
 *   [E] 顶栏              buildTopbar() / refreshTopbar() / clickTab() / markActive()
 *   [F] 布局              findSidebarChain() / placeTopbar() / reserveTopSpace() / forceLayout()
 *   [G] 默认面板          openDefault()：把主区从落地页切到「Harness会话」（或 hash 指定）
 *   [H] 设置页            pruneSettings() 按标题文字裁剪；KEEP_NAV 白名单来自 /wb-ui/config
 *   [I] 首帧遮罩          maskUnknownMain()：面板就位前藏住主区，6 秒上限
 *   [J] 启动              boot()：按时间线跑若干轮 sweep/布局/默认面板，最后写诊断
 *
 * ── 改完怎么验证（别凭肉眼）──────────────────────────────────────────────
 *   页面加载 4.6 秒后自动写 state\boot-diag.json，重点字段：
 *     shellClasses.cssFrameApplied  → 必须是 "flex"（"grid" 说明布局 CSS 没命中）
 *     sidebarVisibleRows            → 必须是 0（原版侧栏没藏干净就会 >0）
 *     topbarTabs / discovered       → 顶栏最终顺序 / 扫到的入口
 *     hasPanel / errors             → 我们的面板是否挂上、有没有 JS 报错
 *   不想自己开浏览器：`python tools\probe-ui.py --root <工作台根>` 会加载一次并读回这些字段。
 *   控制台钩子：__WB_UI__ / __wbSweep() / __wbProbeSettings() / __wbSnapshot('tag')
 * ══════════════════════════════════════════════════════════════════════════ */

;(() => {
  const LABEL = 'wb-ui'
  // 注入层自己的运行时状态（同时暴露到 window.__WB_UI__ 供调试/自诊断读取）
  const state = { hidden: [], sweeps: 0, dismissed: 0, topbar: false }
  window.__WB_UI__ = state
  window.__wbSweep = () => sweep()
  console.info('[wb-ui] injected')

  // 类名工具：**只按后缀取元素**。DSH 的 hash 前缀每个版本都会变，写死前缀 = 换版本后静默失效。
  // 例：bySuffix('frame') 在 alpha.1 上命中 .OSewFq_frame，在 rc.3 上命中 .mP3x-q_frame。
  const bySuffix = (suffix, root = document) => root.querySelector(`[class*="_${suffix}"]`)
  const allBySuffix = (suffix, root = document) => Array.from(root.querySelectorAll(`[class*="_${suffix}"]`))

  // ── [A] 开机自诊断：抓 JS 报错 + 按钮表 + 面板是否就位（只写 state\boot-diag.json）──
  // 目的：面板挂不上时不用猜——直接看是脚本报错、还是入口按钮压根没注册。
  if (!Array.isArray(state.errors)) state.errors = []
  window.addEventListener('error', (e) => {
    const f = String((e && e.filename) || '').split('/').pop()
    state.errors.push(String((e && e.message) || e) + (f ? ' @' + f + ':' + String(e.lineno || '') : ''))
  }, true)
  window.addEventListener('unhandledrejection', (e) => {
    const reason = e && e.reason ? (e.reason.message || String(e.reason)) : '?'
    state.errors.push('rejection: ' + String(reason))
  })
  // React 的渲染错误只走 console.error，不会触发 window.onerror——必须拦一层
  if (!state.consoleErrors) state.consoleErrors = []
  const rawConsoleError = console.error.bind(console)
  console.error = (...args) => {
    try {
      state.consoleErrors.push(args.map((a) => {
        if (a instanceof Error) return a.message
        if (typeof a === 'object' && a !== null) { try { return JSON.stringify(a).slice(0, 200) } catch { return '[object]' } }
        return String(a)
      }).join(' ').slice(0, 400))
    } catch { /* ignore */ }
    try { rawConsoleError(...args) } catch { /* ignore */ }
  }
  if (!state.clickLog) state.clickLog = []
  const bootDiag = () => {
    try {
      const buttons = Array.from(document.querySelectorAll('button, a, [role="button"]'))
        .map((el) => (el.textContent || '').replace(/\s+/g, ' ').trim())
        .filter(Boolean).slice(0, 60)
      const payload = {
        at: new Date().toISOString(),
        url: location.href.slice(0, 120),
        hasPanel: Boolean(document.querySelector('[data-wb-panel]')),
        hasSessionsEntry: buttons.includes('Harness会话'),
        hasPluginsEntry: buttons.includes('插件'),
        topbar: Boolean(document.getElementById('wb-topbar')),
        masked: Boolean(state.mainMasked),
        // 原版侧栏是否还露着：任何 *_panelRow 在我们顶栏之外、且还占着可见矩形 → 说明没藏干净
        sidebarVisibleRows: Array.from(document.querySelectorAll('[class*="_panelRow"]'))
          .filter((el) => !el.closest('#wb-topbar'))
          .filter((el) => {
            const r = el.getBoundingClientRect()
            return r.width > 0 && r.height > 0 && el.offsetParent !== null
          })
          .length,
        // 我们 CSS 里写的选择器在当前版本里是否存在（类名前缀由运行时生成，换版本可能变）
        shellClasses: (() => {
          const out = {}
          const probe = (key, needle) => {
            const el = document.querySelector(`[class*="${needle}"]`)
            out[key] = el ? String(el.className || '').split(/\s+/).find((c) => c.includes(needle)) || '' : ''
          }
          probe('frame', '_frame')
          probe('sidebarCol', '_sidebarCol')
          probe('centerCol', '_centerCol')
          probe('panelRow', '_panelRow')
          out.cssFrameApplied = (() => {
            const el = document.querySelector('[class*="_frame"]')
            if (!el) return 'no-frame'
            return getComputedStyle(el).display
          })()
          return out
        })(),
        defaulted: Boolean(document.getElementById('wb-topbar')) && state.activeMarked ? true : false,
        buttons,
        topbarTabs: Array.from(document.querySelectorAll('#wb-topbar button.wb-tab')).map((b) => b.textContent),
        pluginSectionTabs: ((state.uiConfig && state.uiConfig.extra) || []).slice(0, 12),
        selftestHit: state.selftestHit || null,
        settingsOpen: settingsNavVisible(),
        closeDebug: state.closeDebug || null,
        selftestInfo: state.selftestInfo || null,
        selftestRan: Boolean(state.selftestRan),
        settingsNavCells: allBySuffix('navCell').map((c) => (c.textContent || '').replace(/\s+/g, ' ').trim()).slice(0, 16),
        settingsNavVisible: allBySuffix('navCell')
          .filter((c) => !c.classList.contains('wb-hidden'))
          .map((c) => (c.textContent || '').replace(/\s+/g, ' ').trim()).slice(0, 16),
        discovered: scanSidebarEntries().map((e) => e.label),
        errors: state.errors.slice(0, 12),
        consoleErrors: (state.consoleErrors || []).slice(0, 12),
        clickLog: (state.clickLog || []).slice(0, 8),
      }
      fetch('/wb-ui/dom', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ kind: 'html', name: 'boot-diag.json', html: JSON.stringify(payload, null, 1) }),
      }).catch(() => {})
    } catch { /* 诊断本身不许影响页面 */ }
  }
  window.__wbBootDiag = bootDiag

  // ── [B] 基础样式：顶栏外观 + .wb-hidden 工具类 ────────────────────────────
  // 注意：这里只放"顶栏自己"的样式；布局改造（侧栏不占位、中列撑满）在 ui\workbench.css，
  // 因为那份文件带完整注释、便于别人改外观。两边的类名匹配都必须是后缀形式。
  const style = document.createElement('style')
  style.id = 'wb-ui-hide-style'
  style.textContent = `
    .wb-hidden { display: none !important; }
    #wb-topbar {
      position: fixed; top: 0; left: 0; right: 0; height: 46px; box-sizing: border-box;
      display: flex; align-items: center; gap: 6px; padding: 0 12px;
      background: var(--dsw-alias-bg-base, #16181d);
      border-bottom: 1px solid var(--dsw-alias-border-secondary, #2a2e37);
      z-index: 2147482000;
      font: 12px/1 "Segoe UI", system-ui, sans-serif;
    }
    #wb-topbar .wb-brand {
      font-weight: 600; letter-spacing: .3px; margin-right: 10px;
      color: var(--dsw-alias-label-primary, #e6e6e6); white-space: nowrap;
    }
    #wb-topbar .wb-brand small { font-weight: 400; opacity: .55; margin-left: 6px; font-size: 10px; }
    #wb-topbar button.wb-tab {
      border: 1px solid transparent; background: transparent; cursor: pointer;
      padding: 6px 12px; border-radius: 7px; font: inherit; color: inherit; opacity: .62;
    }
    #wb-topbar button.wb-tab:hover { opacity: 1; background: rgba(64, 132, 255, .12); }
    #wb-topbar button.wb-tab.wb-active {
      opacity: 1; font-weight: 600;
      background: rgba(64, 132, 255, .18);
      box-shadow: inset 0 0 0 1px rgba(64, 132, 255, .55);
    }
    #wb-topbar .wb-spacer { flex: 1; }
    #wb-topbar .wb-dot { width: 7px; height: 7px; border-radius: 50%; background: #4caf50; opacity: .8; }
    .wb-topbar-offset { padding-top: 46px !important; box-sizing: border-box; }
  `
  const attachStyle = () => {
    if (!document.head.contains(style)) document.head.appendChild(style)
  }

  const textOf = (el) => (el.textContent || '').replace(/\s+/g, '').trim()

  // ── 1) 关掉「预览版说明」弹窗 ────────────────────────────────────────
  const DISMISS_TEXTS = ['继续']
  let tries = 0
  const dismiss = () => {
    tries += 1
    if (tries > 40) return
    const target = Array.from(document.querySelectorAll('button')).find((btn) => {
      if (!DISMISS_TEXTS.includes(textOf(btn))) return false
      return Boolean(btn.closest('[role="dialog"], dialog, [class*="modal" i], [class*="dialog" i]'))
    })
    if (target && target.offsetParent !== null) { target.click(); state.dismissed += 1 }
    setTimeout(dismiss, 500)
  }

  // ── 2) 隐藏用不到的原版入口 + 静音无 agent 的报错 toast ───────────────
  const HIDE_TEXTS = ['自动化任务', '工作区', '默认工作区', '新会话']
  const SILENCE_TEXTS = ['新建会话失败', 'no agent factory', 'gateway/internal failed']

  const hide = (el) => {
    if (!el) return
    el.classList.add('wb-hidden')
    el.style.setProperty('display', 'none', 'important')
    const t = textOf(el).slice(0, 16)
    if (t && !state.hidden.includes(t)) state.hidden.push(t)
  }

  // sweep 里不再动布局，只做“隐藏用不到的入口 + 静音 toast”，布局改造交给 placeTopbar
  const sweep = () => {
    state.sweeps += 1
    attachStyle()
    for (const node of document.querySelectorAll('button, a, [role="button"], [role="listitem"], li, div, span')) {
      if (node.closest('#wb-topbar')) continue // 别把自己顶栏的按钮隐藏了
      const text = textOf(node)
      if (!text || text.length > 24) continue
      if (SILENCE_TEXTS.some((n) => text.includes(n))) {
        hide(node.closest('[role="status"], [role="alert"], [class*="toast" i], [class*="alert" i]') || node)
      }
    }
    pruneSettings()
    maskUnknownMain()
    if (state.layoutApplied) return
  }

  // ── 3) 把侧栏藏起来，换成顶部导航 ────────────────────────────────────
  // 顶栏**不写死**：面板清单从应用自己的侧栏入口行动态发现。
  // 任何插件只要注册 `sidebar.panellist` + `main`，就会自动出现在顶栏里，
  // 装/卸插件都不需要再改这个文件（最初把 4 个按钮写死，每装一个新插件都得改代码）。
  const LEFT_ORDER = ['Harness会话', '插件']  // 左边固定顺序；没列到的一律排在左边末尾
  const RIGHT_ORDER = ['状态', '设置']         // 右边，顺序即显示顺序
  const PANEL_TAB_HINTS = { 状态: 'services' } // 点这个入口时顺带把面板内部标签切到哪个
  // 默认打开哪个面板：地址栏可以指定，例如 #wb-panel=插件（token 用完会重定向到 /，
  // query 会被剥掉、hash 会保留，所以深链接必须用 hash）
  const WANT_PANEL = (() => {
    try {
      const fromHash = new URLSearchParams(String(location.hash || '').replace(/^#/, '')).get('wb-panel')
      const fromQuery = new URLSearchParams(location.search).get('panel')
      return String(fromHash || fromQuery || '').trim()
    } catch {
      return ''
    }
  })()
  const DEFAULT_PANEL = WANT_PANEL || 'Harness会话'

  // ── [D] 入口发现：原侧栏里每个入口行 → { label, el } ────────────────────────
  // 类名形如 `hash_panelRow`（后缀固定）。**排除我们自己顶栏里的按钮**，
  // 否则顶栏按钮会被当成"原版入口"再扫一遍，越扫越乱。
  const scanSidebarEntries = () => {
    const rows = Array.from(document.querySelectorAll('[class*="_panelRow"]'))
      .filter((el) => !el.closest('#wb-topbar'))
    const seen = new Set()
    const out = []
    for (const el of rows) {
      const label = textOf(el)
      if (!label || seen.has(label)) continue
      seen.add(label)
      out.push({ label, el, entry: label, panelTab: PANEL_TAB_HINTS[label] })
    }
    return out
  }

  // 发现结果 → 顶栏布局（偏好顺序优先，未知入口自动归左边）
  // 兜底：`设置`这类入口不是面板行（没有 `_panelRow`），扫不到就按文字找按钮——
  // 只对名单里列出来的名字做兜底，新插件仍然靠 `_panelRow` 自动发现。
  const entryFor = (label, byLabel) => {
    const hit = byLabel.get(label)
    if (hit) return hit
    const btn = findButton(label)
    return btn ? { label, el: btn, entry: label, panelTab: PANEL_TAB_HINTS[label] } : null
  }

  // 发现结果 → 左右两栏布局。LEFT_ORDER/RIGHT_ORDER 只管顺序与左右；
  // 名单外的入口一律追加到左边末尾 —— 这就是"装新插件不用改代码"的实现点。
  //
  // 另外：**插件自带的设置分区也要挂顶栏**（用户 2026-10-27 要求：插件设置不该埋在
  // 「设置」弹层里，应该像面板一样从顶栏一键到达）。分区标题来自 /wb-ui/config 的
  // keepNav 里除基础项之外的部分（由 wb.py install-plugin 写入），点它 = 打开设置并切到该分区。
  const settingsSectionTabs = (used) => {
    const extra = (state.uiConfig && Array.isArray(state.uiConfig.extra)) ? state.uiConfig.extra : []
    const out = []
    for (const title of extra) {
      if (!title || used.has(title)) continue   // 已有同名面板入口就不重复
      out.push({ label: title, kind: 'settings', section: title })
      used.add(title)
    }
    return out
  }

  // 内置设置分区：这些**留在设置里**，不要提到顶栏（提到顶栏的是插件加的分区）。
  // 名单按 0.2.1-alpha.1 实测抄的（2026-10-27：`模板` / `内置插件` / `Agent 预设`（中间是半角空格）/
  // `通用设置`）。换 DSH 版本后如果内置项改名，这里不匹配的会被当成插件分区提到顶栏——
  // 不至于坏，但顶栏会多出按钮，见到就补一行。
  const BUILTIN_SETTINGS_NAV = ['通用设置', '模型', '内置插件', 'Agent 预设', '权限', '语言', '外观', '字号大小']

  // 把"插件设置分区"写回服务端（落进 state\ui-config.json）。
  // 必须重试：工作台刚重启那几秒 /wb-ui/config 的 POST 可能还没挂上（405/404），
  // 只发一次就丢，表现是"点一次死按钮消失，刷新又回来"（2026-10-27 踩过）。
  const postSections = (sections, replace, attempt = 0) => {
    fetch('/wb-ui/config', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ sections, replace: Boolean(replace) }),
    })
      .then((res) => { if (!res.ok) throw new Error(String(res.status)) })
      .catch(() => { if (attempt < 3) setTimeout(() => postSections(sections, replace, attempt + 1), 2000) })
  }

  // 目录对账：设置页里**实际存在**的分区才是有效的。插件被卸载后，它留在
  // state\ui-config.json 里的标题会变成"点不开的死按钮"（2026-10-27 卸 dsh-pet 时出现）。
  // 这里在每次打开设置、拿到真实标题列表后，把不存在的从白名单里剔掉并落盘。
  const reconcileSettingsSections = (titles) => {
    const cfg = state.uiConfig
    if (!cfg || !Array.isArray(cfg.extra)) return
    if (!titles || titles.length < 2) return   // 设置还没渲染全时别乱删
    const stale = cfg.extra.filter((t) => !titles.includes(t))
    if (!stale.length) return
    cfg.extra = cfg.extra.filter((t) => titles.includes(t))
    cfg.keepNav = (cfg.keepNav || []).filter((t) => titles.includes(t) || BUILTIN_SETTINGS_NAV.includes(t))
    refreshTopbar()
    postSections(cfg.extra, true)
    state.reconciled = (state.reconciled || []).concat(stale)
  }

  // 客户端自动发现：设置页左侧导航里出现、但不在内置名单里的分区 = 插件加的分区
  // → 立刻当成顶栏入口（这样装带设置分区的插件**不需要任何注册**，
  //   也不需要 wb.py 去猜标题；2026-10-27 之前靠 install-plugin 写 ui-config，猜不到就丢）。
  const discoverSettingsSections = (overlay) => {
    const titles = allBySuffix('navCell', overlay)
      .map((c) => (c.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean)
    const cfg = state.uiConfig || (state.uiConfig = { extra: [], keepNav: [] })
    let changed = false
    for (const t of titles) {
      if (BUILTIN_SETTINGS_NAV.includes(t)) continue
      if (!cfg.extra.includes(t)) { cfg.extra.push(t); changed = true }
      if (!cfg.keepNav.includes(t)) cfg.keepNav.push(t)
    }
    reconcileSettingsSections(titles)
    if (changed) {
      refreshTopbar()
      // 落盘：下次打开页面**不用再先点一次设置**也能有这个顶栏按钮。
      // 服务端只是往 keepNav 里加标题（POST /wb-ui/config），失败也无所谓——
      // 下次打开设置时会再发现一次。
      postSections(cfg.extra, false)
    }
    return titles
  }

  const planTabs = () => {
    const entries = scanSidebarEntries()
    const byLabel = new Map(entries.map((e) => [e.label, e]))
    const left = []
    for (const label of LEFT_ORDER) {
      const hit = entryFor(label, byLabel)
      if (hit) left.push(hit)
    }
    for (const e of entries) {
      if (LEFT_ORDER.includes(e.label) || RIGHT_ORDER.includes(e.label)) continue
      left.push(e)
    }
    const used = new Set([...left, ...RIGHT_ORDER].map((t) => t.label))
    for (const tab of settingsSectionTabs(used)) left.push(tab)
    const right = []
    for (const label of RIGHT_ORDER) {
      const hit = entryFor(label, byLabel)
      if (hit) right.push(hit)
    }
    return { left, right, all: [...left, ...right] }
  }

  const findButton = (text) =>
    Array.from(document.querySelectorAll('button, a, [role="button"]')).find((el) => textOf(el) === text)

  // 找“原侧栏”：从「设置」入口往上走，把所有“窄而高”的容器都收集起来（整条侧栏链路）
  const NARROW = 460
  const findSidebarChain = () => {
    // 锚点优先用「设置」按钮；但 0.2.1-rc.3 起设置被收进「更多」菜单、没有独立按钮，
    // 这时退回“任意一个侧栏面板行”——否则整条原版侧栏都藏不掉，客户会看到原版左栏。
    let anchor = findButton('设置')
    if (!anchor) {
      const rows = Array.from(document.querySelectorAll('[class*="_panelRow"]'))
        .filter((el) => !el.closest('#wb-topbar'))
      anchor = rows[0] || null
    }
    if (!anchor) return []
    const chain = []
    let node = anchor
    for (let depth = 0; depth < 9 && node; depth += 1) {
      if (node.id === 'wb-topbar') break
      const rect = node.getBoundingClientRect()
      if (rect.height > window.innerHeight * 0.5 && rect.width > 100 && rect.width < NARROW) chain.push(node)
      node = node.parentElement
    }
    return chain
  }

  // 侧栏藏掉后，让相邻的主内容撑满
  const expandMain = (hiddenEls) => {
    if (!hiddenEls.length) return
    const outermost = hiddenEls[hiddenEls.length - 1]
    const layout = outermost.parentElement
    if (!layout) return
    for (const child of Array.from(layout.children)) {
      if (hiddenEls.includes(child) || child.classList.contains('wb-hidden')) continue
      child.style.setProperty('flex', '1 1 auto', 'important')
      child.style.setProperty('width', '100%', 'important')
      child.style.setProperty('min-width', '0', 'important')
    }
  }

  const applyPanelTab = (id) => {
    if (!id) return
    const fire = () => {
      try {
        if (typeof window.__wbApiSelect === 'function') window.__wbApiSelect(id)
        window.dispatchEvent(new CustomEvent('wb:select-tab', { detail: id }))
      } catch { /* 面板还没挂载就算了 */ }
    }
    fire()
    setTimeout(fire, 250)
    setTimeout(fire, 700)
  }

  // 打开「设置」——跨版本差异：0.2.1-alpha.1 顶栏/侧栏有独立「设置」按钮，
  // 而 0.2.1-rc.3 把设置收进了「更多」菜单里（没有独立按钮）。
  // 所以这里先直点，找不到就点「更多」再点里面的设置（2026-10-27 在 rc.3 床上踩到）。
  const openSettingsPanel = () => {
    const direct = findButton('设置')
    if (direct) { direct.click(); return true }
    for (const label of ['更多', 'More']) {
      const more = findButton(label)
      if (!more) continue
      more.click()
      setTimeout(() => {
        const inside = findButton('设置')
        if (inside) inside.click()
      }, 250)
      return true
    }
    return false
  }

  // 打开「设置」并切到某个分区（插件自带分区的顶栏入口用它）。
  // 为什么这么绕：插件分区是设置在弹层里渲染的，没有独立入口；
  // 我们能做的正确事就是"打开设置 + 点它左侧导航里那一格"，而不是伪造一个面板。
  const openSettingsSection = (title) => {
    openSettingsPanel()
    const step = (attempt) => {
      const overlay = settingsRoot()
      // 优先在设置容器里找；找不到就退到全文档（有些版本导航栏不在 overlay 内部）
      const cells = (overlay ? allBySuffix('navCell', overlay) : []).concat()
      const pool = cells.length ? cells : allBySuffix('navCell')
      state.selftestInfo = { attempt, hasOverlay: Boolean(overlay), pool: pool.length, title }
      const cell = pool.find((c) => (c.textContent || '').trim() === title)
      if (cell) {
        cell.click()
        markActive(title)
        state.selftestHit = title   // 只给自检用：证明"找到了格子并点到了"
        return
      }
      if (attempt < 10) setTimeout(() => step(attempt + 1), 150)
      else {
        // 分区已经不在了（插件被卸载）→ 把这个死按钮从顶栏拿掉，别让用户点到空气
        const cfg = state.uiConfig
        if (pool.length > 0 && cfg && Array.isArray(cfg.extra) && cfg.extra.includes(title)) {
          cfg.extra = cfg.extra.filter((t) => t !== title)
          refreshTopbar()
          postSections(cfg.extra, true)
        }
        state.selftestInfo = { attempt, hasOverlay: Boolean(overlay), pool: pool.length, title, missing: true }
      }
    }
    setTimeout(() => step(0), 200)
  }

  // 切到面板时先把设置弹层关掉。
  // 用户 2026-10-27 报的 bug：「点了桌宠配置以后再点插件，配置界面没有自动关闭掉」——
  // 设置是我们替用户打开的，切走时必须由我们负责关，否则弹层会盖在新面板上。
  // 「设置弹层开着没有」的**唯一可靠判据**：设置左侧导航格子（`*_navCell`）是否可见。
  // 不能用「overlay 元素存在 / 可见」——页面上还有别的 overlay（遮罩、toast），
  // 基线（没开设置）时也会命中，导致自检永远报"开着"（2026-10-27 踩过）。
  const settingsNavVisible = () => allBySuffix('navCell').some((el) => {
    const rect = el.getBoundingClientRect()
    return rect.width > 10 && rect.height > 10
  })

  // 设置弹层容器：从可见的导航格子往上找，找到"内部含关闭按钮"的那一层
  const settingsContainer = () => {
    const cell = allBySuffix('navCell').find((el) => {
      const rect = el.getBoundingClientRect()
      return rect.width > 10 && rect.height > 10
    })
    if (!cell) return null
    let node = cell
    for (let depth = 0; depth < 12 && node; depth += 1) {
      if (node.querySelector && node.querySelector('[class*="_close"]')) return node
      node = node.parentElement
    }
    return cell.closest('[class*="_overlay"]') || cell
  }

  // 切到面板时先把设置弹层关掉（用户 2026-10-27 报的 bug：
  // 「点了桌宠配置以后再点插件，配置界面没有自动关闭掉」）。
  // 设置是我们替用户打开的，切走时必须由我们负责关，否则弹层会盖在新面板上。
  const closeSettingsIfOpen = () => {
    const container = settingsContainer()
    state.closeDebug = { navVisible: settingsNavVisible(), container: Boolean(container) }
    if (!container) return false
    const closeBtn = container.querySelector('[class*="_close"]') || bySuffix('close')
    if (closeBtn) {
      try {
        closeBtn.click()
        state.closeDebug.clicked = String(closeBtn.className || "").slice(0, 60)
        return true
      } catch (err) {
        state.closeDebug.error = String(err && err.message ? err.message : err).slice(0, 80)
      }
    }
    try {
      for (const target of [document, window]) {
        target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }))
      }
      state.closeDebug.escaped = true
    } catch { /* 兜底失败就算了，不影响切面板 */ }
    return false
  }

  const clickTab = (tab) => {
    if (tab.kind === 'settings') return openSettingsSection(tab.section)
    closeSettingsIfOpen()
    // 优先按文字现找（React 重绘会换掉行元素），找不到再用建栏时缓存的元素
    const btn = findButton(tab.label) || (tab.el && tab.el.isConnected ? tab.el : null)
    if (btn) btn.click()
    applyPanelTab(tab.panelTab)
    markActive(tab.label)
  }

  const markActive = (label) => {
    state.activeTab = label
    const bar = document.getElementById('wb-topbar')
    if (!bar) return
    for (const node of bar.querySelectorAll('button.wb-tab')) {
      node.classList.toggle('wb-active', node.dataset.wbTab === label)
    }
  }

  const makeTab = (tab) => {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'wb-tab'
    btn.dataset.wbTab = tab.label
    // 区分"面板入口"和"插件设置分区入口"：两者外观一样，但点击行为不同，
    // 自检/调试需要能分别选到（同名时尤其重要——插件市场既是面板又是设置分区）。
    btn.dataset.wbKind = tab.kind || 'panel'
    btn.textContent = tab.label
    btn.addEventListener('click', () => clickTab(tab))
    return btn
  }

  const buildTopbar = (plan) => {
    const existing = document.getElementById('wb-topbar')
    if (existing) existing.remove()
    const bar = document.createElement('div')
    bar.id = 'wb-topbar'
    bar.dataset.wbSig = plan.all.map((t) => t.label).join('|')
    const brand = document.createElement('div')
    brand.className = 'wb-brand'
    brand.innerHTML = `DSH 工作台<small>${state.port || 59430}</small>`
    bar.appendChild(brand)

    for (const tab of plan.left) {
      bar.appendChild(makeTab(tab))
    }

    const spacer = document.createElement('div')
    spacer.className = 'wb-spacer'
    bar.appendChild(spacer)

    for (const tab of plan.right) {
      bar.appendChild(makeTab(tab))
    }

    const dot = document.createElement('span')
    dot.className = 'wb-dot'
    dot.title = '工作台在线'
    bar.appendChild(dot)

    document.body.appendChild(bar)
    state.topbar = true
    if (state.activeTab) markActive(state.activeTab)
    return bar
  }

  // 入口集合变了才重建顶栏：装/卸插件、面板延迟注册都会自动跟上
  const refreshTopbar = () => {
    const plan = planTabs()
    if (!plan.all.length) return document.getElementById('wb-topbar')
    const sig = plan.all.map((t) => t.label).join('|')
    const bar = document.getElementById('wb-topbar')
    if (bar && bar.dataset.wbSig === sig) return bar
    return buildTopbar(plan)
  }

  // 让主内容区给顶栏留出高度：给 body 加顶栏高度的 padding（不动应用内部结构，
  // 上次把 #root 搬进包装容器导致高度链断裂、整页空白，已弃用）
  const reserveTopSpace = () => {
    const bar = document.getElementById('wb-topbar')
    if (!bar) return
    const h = bar.getBoundingClientRect().height || 46
    document.body.style.setProperty('padding-top', `${h}px`, 'important')
    document.body.style.setProperty('box-sizing', 'border-box', 'important')
    state.reserved = h
  }

  // ── [F] 布局：把原侧栏藏掉 → 建顶栏 → 给 body 让出 46px ──────────────────
  // 只"藏"不禁用：禁用一个提供服务的插件（如 ui-workspace）会让整页 pending。
  const placeTopbar = () => {
    // 整条侧栏链路都藏掉（只藏、不禁用插件——禁用一个提供服务的插件会让整页崩）
    const chain = findSidebarChain()
    if (chain.length) {
      for (const el of chain) hide(el)
      expandMain(chain)
      state.sidebarHides = chain.length
    }
    refreshTopbar()
    reserveTopSpace()
    if (!state.activeMarked && findButton(DEFAULT_PANEL)) {
      state.activeMarked = true
      markActive(DEFAULT_PANEL)
    }
  }

  // ── 4) 默认打开「状态」（工作台核心面板，不再单列成工具入口）──────────
  let defaulted = false
  const openDefault = () => {
    if (defaulted) return
    // 注意：必须用 textContent 而不是 innerText —— 遮罩用 visibility:hidden 藏主区，
    // 被藏元素没有 innerText，用 innerText 判断会永远为假（曾因此点击永不触发、面板挂不上）。
    // 例外：地址栏明确指定了 ?panel=xxx 时不看落地页文字，直接切过去（深链接/收藏要靠它）。
    if (!WANT_PANEL && !/选择工作区|探索未至之境/.test(document.body ? document.body.textContent : '')) return
    const btn = findButton(DEFAULT_PANEL)
    if (!btn) {
      state.clickLog.push({ t: Date.now(), found: false })
      return
    }
    defaulted = true
    state.clickLog.push({ t: Date.now(), found: true, tag: btn.tagName, cls: String(btn.className || '').slice(0, 60), text: textOf(btn) })
    btn.click()
    markActive(DEFAULT_PANEL)
    setTimeout(() => {
      const center = bySuffix('centerCol')
      state.clickLog.push({
        t: Date.now(),
        after: true,
        hasPanel: Boolean(document.querySelector('[data-wb-panel]')),
        centerHead: center ? (center.innerText || '').replace(/\s+/g, ' ').slice(0, 60) : 'no-center',
      })
    }, 900)
  }

  // ── 5) 启动 ────────────────────────────────────────────────────────
  let pending = false
  const observe = () => {
    const observer = new MutationObserver(() => {
      if (pending) return
      pending = true
      setTimeout(() => { pending = false; sweep() }, 200)
    })
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] })
  }

  // ── 5) 把真实 DOM 结构上报（只用于设计样式，不改任何东西）──────────────
  const snapshot = (tag) => {
    const nodes = []
    const walk = (el, depth) => {
      if (!el || nodes.length > 3000 || depth > 14) return
      const r = el.getBoundingClientRect()
      nodes.push({
        d: depth,
        tag: el.tagName.toLowerCase(),
        id: el.id || '',
        cls: String(el.className || '').slice(0, 140),
        x: Math.round(r.x), y: Math.round(r.y),
        w: Math.round(r.width), h: Math.round(r.height),
        text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
        role: el.getAttribute('role') || '',
      })
      for (const child of el.children) walk(child, depth + 1)
    }
    walk(document.body, 0)
    fetch('/wb-ui/dom', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tag: tag || 'after', at: new Date().toISOString(), url: location.href.slice(0, 120), viewport: { w: innerWidth, h: innerHeight }, nodes }),
    }).then(() => console.info(`[wb-ui] dom snapshot (${tag}) sent:`, nodes.length)).catch(() => {})
  }
  window.__wbSnapshot = snapshot

  // 布局兜底：CSS 已经用后缀选择器做了同样的事，这里只是"CSS 没生效时的保险"。
  // 判断依据是**中列实际宽度**，不依赖任何类名前缀。
  const forceLayout = () => {
    const frame = bySuffix('frame')
    const center = bySuffix('centerCol')
    if (!frame || !center) return false
    if (center.getBoundingClientRect().width > window.innerWidth * 0.7) {
      state.layoutOk = true
      return true
    }
    frame.style.setProperty('display', 'flex', 'important')
    frame.style.setProperty('flex-direction', 'row', 'important')
    center.style.setProperty('flex', '1 1 auto', 'important')
    center.style.setProperty('width', 'auto', 'important')
    center.style.setProperty('max-width', 'none', 'important')
    center.style.setProperty('min-width', '0', 'important')
    for (const suffix of ['sidebarCol', 'rightbarCol', 'handle']) {
      for (const el of allBySuffix(suffix)) el.style.setProperty('display', 'none', 'important')
    }
    state.layoutForced = center.getBoundingClientRect().width
    return true
  }

  // 设置面板一打开就自动拍一张结构快照，方便按真实标签裁剪分区
  let settingsCaptured = false
  const watchSettings = () => {
    if (settingsCaptured) return
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"], dialog'))
    const hit = dialogs.find((d) => /设置/.test(d.textContent || ''))
    if (hit) {
      settingsCaptured = true
      setTimeout(() => snapshot('settings'), 400)
    }
  }
  window.__wbCaptureSettings = () => { settingsCaptured = false; watchSettings() }

  // 自动探测设置面板结构：自己点开「设置」→ 拍快照 → 关掉 → 回到默认面板
  // （不需要用户手动点，刷新一次即可）
  let probed = false
  const probeSettings = () => {
    if (probed) return
    if (!openSettingsPanel()) return
    probed = true
    setTimeout(() => {
      pruneSettings()
    maskUnknownMain() // 先裁剪，再导出，导出的结果就是最终可见状态
      snapshot('settings')
      const content = settingsRoot()
      if (content) {
        fetch('/wb-ui/dom', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ kind: 'html', name: 'settings.html', html: content.outerHTML }),
        }).then(() => console.info('[wb-ui] settings html dumped')).catch(() => {})
      }
      const closeBtn = bySuffix('close')
      if (closeBtn && !(location.search + location.hash).includes('keep-settings')) closeBtn.click()
      setTimeout(() => {
        const back = findButton(DEFAULT_PANEL)
        if (back) { back.click(); markActive(DEFAULT_PANEL) }
      }, 250)
    }, 900)
  }
  window.__wbProbeSettings = () => { probed = false; probeSettings() }

  // ── 6) 裁剪设置页：只保留 语言 / 外观 / 字号大小 ─────────────────────
  // 设置项来自不同插件、结构和类名都不一样，唯一稳定的是「标题文字」：
  // 找到标题文本 → 隐藏它最近的 _row / _group / _setting 容器。
  const KEEP_SETTINGS = ['语言', '外观', '字号大小']
  const REMOVE_SETTINGS = ['权限', '工作步骤展示', '显示代码工作视图', '显示代码工作图宽', '快捷键', '繁忙时的发送行为', '性能与用量']
  // 设置页左侧导航只留这些。基础白名单写在这里；**第三方插件加的分区标题由
  // wb.py install-plugin 自动写进 state\ui-config.json（/wb-ui/config 读回来）**，
  // 所以装带设置分区的插件不再需要改这个文件。
  const BASE_KEEP_NAV = ['通用设置']
  const KEEP_NAV = BASE_KEEP_NAV.slice()
  const loadUiConfig = async () => {
    try {
      const res = await fetch('/wb-ui/config', { headers: { accept: 'application/json' } })
      const body = await res.json()
      const extra = Array.isArray(body && body.keepNav) ? body.keepNav.filter((x) => typeof x === 'string' && x.trim()) : []
      for (const title of extra) {
        if (!KEEP_NAV.includes(title)) KEEP_NAV.push(title)
      }
      state.uiConfig = { extra, keepNav: KEEP_NAV.slice() }
      // 端口从服务端读（客户机上可能是 59431 之类），别在界面里写死 59430
      if (body && Number.isInteger(body.port) && body.port > 0) {
        state.port = body.port
        document.documentElement.style.setProperty('--wb-port', String(body.port))
        const brand = document.querySelector('#wb-topbar .wb-brand small')
        if (brand) brand.textContent = String(body.port)
      }
    } catch { /* 读不到就用基础白名单 / 默认端口 */ }
  }

  // 精确找“行容器”：类名必须以 _row/_group/_setting 结尾（不能用 *="_row"，
  // 那会匹配到 _rowText / _rowTitle 这类文字容器，结果是把文字藏了、行还留着）
  const findRowContainer = (el) => {
    let node = el
    for (let depth = 0; depth < 6 && node; depth += 1) {
      const cls = String(node.className || '')
      if (/(^|\s)[\w-]+_(row|group|setting)(\s|$)/.test(cls)) return node
      node = node.parentElement
    }
    return null
  }

  // 设置页根节点：优先找**内部含导航格子（`*_navCell`）**的 overlay——
  // 只按 `_overlay` 后缀找会抓到别的遮罩（toast/掩码），那样既裁不到设置、也点不到分区
  // （2026-10-27 自检时踩到：格子明明在，却因为根节点抓错而"找不到格子"）。
  const settingsRoot = () => {
    const withNav = allBySuffix('overlay').filter((el) => el.querySelector('[class*="_navCell"]'))
    if (withNav.length) return withNav[withNav.length - 1]   // 取最外层那个
    const dialog = Array.from(document.querySelectorAll('[role="dialog"], dialog'))
      .find((d) => /设置/.test(d.textContent || '') && d.querySelector('[class*="_navCell"]'))
    return dialog || bySuffix('overlay') || null
  }

  const pruneSettings = () => {
    const overlay = settingsRoot()
    if (!overlay) return
    // 每次打开设置都扫一遍左侧导航：插件新加的分区立刻进顶栏（不需要任何注册）
    const navTitles = discoverSettingsSections(overlay)
    let hidden = 0
    for (const el of overlay.querySelectorAll('div[class*="_title"], div[class*="_settingTitle"]')) {
      const text = (el.textContent || '').trim()
      if (!REMOVE_SETTINGS.includes(text)) continue
      const row = findRowContainer(el)
      if (row) { row.classList.add('wb-hidden'); hidden += 1 }
    }
    // 直接遍历设置区里的每一行，按“行文本以标题开头”兜底（有些行没有 _row 类名）
    const section = bySuffix('section', overlay) || bySuffix('options', overlay)
    if (section) {
      for (const child of section.children) {
        const text = (child.textContent || '').replace(/\s+/g, ' ').trim()
        // only short row text: the wrapper containing every row is long, never hide it
        if (text.length < 160 && REMOVE_SETTINGS.some((k) => text.startsWith(k))) { child.classList.add('wb-hidden'); hidden += 1 }
      }
    }
    // 注意：[data-slot=settings.general.item] 只有一个，且包住整个通用设置区，
    // 绝不能按它的文字判断——那会把整块内容一起藏掉（踩过）。逐项隐藏只靠上面的标题匹配。

    // 插件设置分区已经提到顶栏 → 设置弹层里不再重复列一遍（用户 2026-10-27：
    // 「这几个插件的设置窗口位置不太好，应该放到顶栏」）。元素只是隐藏，程序化 click
    // 依然有效，所以顶栏入口点进来照样能切到该分区。
    const promoted = (state.uiConfig && state.uiConfig.extra) || []
    for (const cell of allBySuffix('navCell', overlay)) {
      const text = (cell.textContent || '').replace(/\s+/g, ' ').trim()
      const hide = !KEEP_NAV.includes(text) || promoted.includes(text)
      cell.classList.toggle('wb-hidden', hide)
    }
    for (const actions of allBySuffix('actions', overlay)) {
      actions.classList.add('wb-hidden') // “打开配置文件”，工作台用不上
    }
    state.settingsHidden = hidden
    if (state.diagSent) return
    state.diagSent = true
    try {
      const probe = []
      for (const el of overlay.querySelectorAll('div[class*="_title"], div[class*="_settingTitle"]')) {
        const tx = (el.textContent || '').trim()
        if (!REMOVE_SETTINGS.includes(tx)) continue
        const row = findRowContainer(el)
        probe.push({ title: tx, cls: String(el.className), rowCls: row ? String(row.className) : null, rowHidden: row ? row.classList.contains('wb-hidden') : null })
      }
      const titles = Array.from(overlay.querySelectorAll('div[class*="_title"], div[class*="_settingTitle"]'))
        .map((el) => (el.textContent || '').trim()).filter(Boolean).slice(0, 40)
      fetch('/wb-ui/dom', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ kind: 'html', name: 'diag.json', html: JSON.stringify({ titles, hidden, probe, removeList: REMOVE_SETTINGS }) }),
      }).catch(() => {})
    } catch (e) { /* ignore */ }
  }
  window.__wbPruneSettings = pruneSettings

  // ── 7) 面板就位前遮住主区域，避免"探索未至之境"空状态闪一下 ─────────────
  // 我们的面板根节点都带 data-wb-panel；在它出现之前，把主列的子元素先藏起来。
  // 6 秒后无论如何都放开，避免面板异常时整块区域永久空白。
  const bootAt = Date.now()
  const maskUnknownMain = () => {
    const center = bySuffix('centerCol')
    if (!center) return
    const ours = center.querySelector('[data-wb-panel]')
    if (ours) {
      if (state.mainMasked) {
        for (const el of center.children) el.style.removeProperty('visibility')
        state.mainMasked = false
      }
      return
    }
    if (Date.now() - bootAt > 6000) {
      if (state.mainMasked) {
        for (const el of center.children) el.style.removeProperty('visibility')
        state.mainMasked = false
      }
      return
    }
    for (const el of center.children) el.style.setProperty('visibility', 'hidden', 'important')
    state.mainMasked = true
  }

  // ── [J] 启动：一条时间线，不要随意改顺序 ──────────────────────────────────
  //  0ms     注入样式、读裁剪白名单、开始关「预览版说明」弹窗、第一轮 sweep（只清 toast）
  //  1.6s    拍"改造前"的 DOM 快照（诊断用）
  //  2.2s    藏侧栏 + 建顶栏 + 布局兜底 + sweep   ← 关键一步
  //  3.4s    拍"改造后"快照
  //  150/450/900/1800/3000ms  反复 sweep + 布局兜底 + openDefault()
  //          （React 会重渲染，单次操作不可靠；openDefault 只在落地页才切面板）
  //  4.6s    写 boot-diag.json（面板结果 + 类名探测 + 报错）
  //  每 2.5s 兜底轮询：sweep + refreshTopbar + watchSettings
  const boot = () => {
    attachStyle()
    // 标题双保险：注入层已经改写了 <title>，这里再设一次（SPA 可能自己改标题）
    try {
      document.title = 'DSH 工作台'
      new MutationObserver(() => {
        if (document.title !== 'DSH 工作台') document.title = 'DSH 工作台'
      }).observe(document.querySelector('title') || document.head, { childList: true, subtree: true, characterData: true })
    } catch { /* 忽略 */ }
    loadUiConfig().finally(() => {
      // 配置回来之后顶栏可能要多出「插件设置分区」按钮 → 立刻重排一次
      try { refreshTopbar() } catch { /* 顶栏还没建，下面定时器会补 */ }
    }) // 先读白名单与插件设置分区（异步，不阻塞）；读了之后裁剪和顶栏都用新列表
    dismiss()
    sweep() // 第一轮：先只处理 toast / 弹窗，不动布局
    observe()
    // 顺序很重要：先拍“隐藏侧栏前”的原始布局，再改造，再拍一张对照
    setTimeout(() => snapshot('baseline'), 1600)
    setTimeout(() => { placeTopbar(); forceLayout(); sweep() }, 2200)
    setTimeout(() => snapshot('after'), 3400)
    setTimeout(() => { sweep(); forceLayout(); openDefault() }, 150)
    setTimeout(() => { sweep(); forceLayout(); openDefault() }, 450)
    setTimeout(() => { sweep(); forceLayout(); openDefault() }, 900)
    setTimeout(() => { sweep(); forceLayout(); openDefault() }, 1800)
    setTimeout(() => { sweep(); forceLayout(); openDefault() }, 3000)
    // 自检：`?wb-selftest=settings` 时自动点第一个插件设置分区，并把结果写进 boot-diag。
    // 只用于验证"顶栏入口 → 设置分区"这条链路，正常使用不会触发。
    // 注意：自检模式下只写一次 diag（4.5s），否则首次 4.6s 的那份会先被探针读走、
    // 看不到 selftestHit（2026-10-27 踩过）。
    const SELFTEST = (location.search + location.hash).includes('wb-selftest=')
    if (SELFTEST) {
      const mode = (location.hash.match(/wb-selftest=([a-z]+)/) || [])[1] || 'settings'
      setTimeout(() => {
        state.selftestRan = true
        if (mode === 'switch') {
          // 先点插件设置按钮（打开设置弹层），1 秒后再点某个面板入口，
          // 期望：设置被自动关掉（diag 里的 settingsOpen 应为 false）
          const bars = Array.from(document.querySelectorAll('#wb-topbar button.wb-tab'))
          const sectionTab = bars.filter((b) => b.dataset.wbKind === 'settings')[0]
          if (sectionTab) sectionTab.click()
          setTimeout(() => {
            const panelTab = bars.find((b) => b.dataset.wbKind !== 'settings' && b.textContent === '插件')
            if (panelTab) panelTab.click()
          }, 1000)
          return
        }
        if (mode === 'tab') {
          // 点**顶栏上那个插件设置按钮**，走真实用户路径
          const extra = (state.uiConfig && state.uiConfig.extra) || []
          const bars = Array.from(document.querySelectorAll('#wb-topbar button.wb-tab'))
          const sectionTabs = bars.filter((b) => b.dataset.wbKind === 'settings')
          const btn = sectionTabs[0] || bars.find((b) => extra.includes(b.textContent))
          if (btn) btn.click()
          return
        }
        // mode=settings：点开设置 → 等它渲染 → 找**第一个非内置分区** → 点它
        openSettingsPanel()
        setTimeout(() => {
          const overlay = settingsRoot()
          const cells = overlay ? allBySuffix('navCell', overlay) : []
          const hit = cells.find((c) => {
            const t = (c.textContent || '').replace(/\s+/g, ' ').trim()
            return t && !BUILTIN_SETTINGS_NAV.includes(t)
          })
          if (hit) {
            const title = (hit.textContent || '').replace(/\s+/g, ' ').trim()
            hit.click()
            markActive(title)
            state.selftestHit = title
          }
        }, 1200)
      }, 2200)
      // 自检时顺带把设置弹层的 DOM 导到 state\settings-<版本>.html，
      // 方便跨版本对照导航区结构（rc.3 的导航格子类名和 alpha.1 不一样）。
      setTimeout(() => {
        try {
          const overlay = bySuffix('overlay')
          if (overlay) {
            fetch('/wb-ui/dom', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ kind: 'html', name: 'settings-selftest.html', html: overlay.outerHTML }),
            }).catch(() => {})
          }
        } catch { /* 忽略 */ }
      }, 3200)
      setTimeout(bootDiag, 4500)
    } else {
      setTimeout(bootDiag, 4600)
    }
    // 自动探测只在调试时用：默认关闭，需要时控制台执行 __wbProbeSettings()
    if ((location.search + location.hash).includes('probe-settings')) setTimeout(probeSettings, 5200)
    setInterval(() => { sweep(); refreshTopbar(); watchSettings() }, 2500)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot)
  } else {
    boot()
  }
})();
