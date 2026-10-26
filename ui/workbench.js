/* ────────────────────────────────────────────────────────────────
 * 工作台 UI 注入脚本（改完刷新页面即生效；删掉本文件即完全恢复原样）
 *
 * 改造目标：把原版左侧栏换成顶部横向导航条。
 * 思路：不重写任何面板逻辑——只把原侧栏藏起来，另建一条顶栏，
 *       顶栏按钮点击时转去点原侧栏里的同名入口（DOM click 对隐藏元素同样有效）。
 * ──────────────────────────────────────────────────────────────── */

;(() => {
  const LABEL = 'wb-ui'
  const state = { hidden: [], sweeps: 0, dismissed: 0, topbar: false }
  window.__WB_UI__ = state
  window.__wbSweep = () => sweep()
  console.info('[wb-ui] injected')

  // ── 开机自诊断：抓 JS 报错 + 按钮表 + 面板是否就位（只写 state\boot-diag.json）──
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
        defaulted: Boolean(document.getElementById('wb-topbar')) && state.activeMarked ? true : false,
        buttons,
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

  // ── 0) 基础样式 ─────────────────────────────────────────────────────
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
  // 顶栏标签分组：左侧（Harness会话 / 插件），右侧（状态 / 设置）
  const TABS_LEFT = [
    { label: 'Harness会话', entry: 'Harness会话' },
    { label: '插件', entry: '插件' },
  ]
  const TABS_RIGHT = [
    { label: '状态', entry: '状态', panelTab: 'services' },
    { label: '设置', entry: '设置' },
  ]
  const TABS = [...TABS_LEFT, ...TABS_RIGHT]
  const DEFAULT_PANEL = 'Harness会话'

  const findButton = (text) =>
    Array.from(document.querySelectorAll('button, a, [role="button"]')).find((el) => textOf(el) === text)

  // 找“原侧栏”：从「设置」入口往上走，把所有“窄而高”的容器都收集起来（整条侧栏链路）
  const NARROW = 460
  const findSidebarChain = () => {
    const anchor = findButton('设置')
    if (!anchor) return []
    const chain = []
    let node = anchor
    for (let depth = 0; depth < 9 && node; depth += 1) {
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

  const clickTab = (tab) => {
    const btn = findButton(tab.entry)
    if (btn) btn.click()
    applyPanelTab(tab.panelTab)
    markActive(tab.label)
  }

  const markActive = (label) => {
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
    btn.textContent = tab.label
    btn.addEventListener('click', () => clickTab(tab))
    return btn
  }

  const buildTopbar = () => {
    if (document.getElementById('wb-topbar')) return document.getElementById('wb-topbar')
    const bar = document.createElement('div')
    bar.id = 'wb-topbar'
    const brand = document.createElement('div')
    brand.className = 'wb-brand'
    brand.innerHTML = 'DSH 工作台<small>59430</small>'
    bar.appendChild(brand)

    for (const tab of TABS_LEFT) {
      bar.appendChild(makeTab(tab))
    }

    const spacer = document.createElement('div')
    spacer.className = 'wb-spacer'
    bar.appendChild(spacer)

    for (const tab of TABS_RIGHT) {
      bar.appendChild(makeTab(tab))
    }

    const dot = document.createElement('span')
    dot.className = 'wb-dot'
    dot.title = '工作台在线'
    bar.appendChild(dot)

    document.body.appendChild(bar)
    state.topbar = true
    return bar
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

  const placeTopbar = () => {
    // 整条侧栏链路都藏掉（只藏、不禁用插件——禁用一个提供服务的插件会让整页崩）
    const chain = findSidebarChain()
    if (chain.length) {
      for (const el of chain) hide(el)
      expandMain(chain)
      state.sidebarHides = chain.length
    }
    buildTopbar()
    reserveTopSpace()
    if (!state.activeMarked && findButton(DEFAULT_PANEL)) {
      state.activeMarked = true
      markActive(TABS.find((t) => t.entry === DEFAULT_PANEL)?.label || DEFAULT_PANEL)
    }
  }

  // ── 4) 默认打开「状态」（工作台核心面板，不再单列成工具入口）──────────
  let defaulted = false
  const openDefault = () => {
    if (defaulted) return
    // 注意：必须用 textContent 而不是 innerText —— 遮罩用 visibility:hidden 藏主区，
    // 被藏元素没有 innerText，用 innerText 判断会永远为假（曾因此点击永不触发、面板挂不上）。
    if (!/选择工作区|探索未至之境/.test(document.body ? document.body.textContent : '')) return
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
      const center = document.querySelector('.OSewFq_centerCol')
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

  // 布局兜底：如果 3 秒后中列还没吃满宽度，就用内联样式硬掰（grid → flex）
  const forceLayout = () => {
    const frame = document.querySelector('.OSewFq_frame')
    const center = document.querySelector('.OSewFq_centerCol')
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
    for (const cls of ['.OSewFq_sidebarCol', '.OSewFq_rightbarCol', '.OSewFq_handle']) {
      const el = document.querySelector(cls)
      if (el) el.style.setProperty('display', 'none', 'important')
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
    const openBtn = findButton('设置')
    if (!openBtn) return
    probed = true
    openBtn.click()
    setTimeout(() => {
      pruneSettings()
    maskUnknownMain() // 先裁剪，再导出，导出的结果就是最终可见状态
      snapshot('settings')
      const content = document.querySelector('.ZCYAFq_overlay')
      if (content) {
        fetch('/wb-ui/dom', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ kind: 'html', name: 'settings.html', html: content.outerHTML }),
        }).then(() => console.info('[wb-ui] settings html dumped')).catch(() => {})
      }
      const closeBtn = document.querySelector('.ZCYAFq_close')
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
  const KEEP_NAV = ['通用设置']

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

  const pruneSettings = () => {
    const overlay = document.querySelector('.ZCYAFq_overlay')
    if (!overlay) return
    let hidden = 0
    for (const el of overlay.querySelectorAll('div[class*="_title"], div[class*="_settingTitle"]')) {
      const text = (el.textContent || '').trim()
      if (!REMOVE_SETTINGS.includes(text)) continue
      const row = findRowContainer(el)
      if (row) { row.classList.add('wb-hidden'); hidden += 1 }
    }
    // 直接遍历设置区里的每一行，按“行文本以标题开头”兜底（有些行没有 _row 类名）
    const section = overlay.querySelector('.JZe3aa_section') || overlay.querySelector('.ZCYAFq_options')
    if (section) {
      for (const child of section.children) {
        const text = (child.textContent || '').replace(/\s+/g, ' ').trim()
        // only short row text: the wrapper containing every row is long, never hide it
        if (text.length < 160 && REMOVE_SETTINGS.some((k) => text.startsWith(k))) { child.classList.add('wb-hidden'); hidden += 1 }
      }
    }
    // 注意：[data-slot=settings.general.item] 只有一个，且包住整个通用设置区，
    // 绝不能按它的文字判断——那会把整块内容一起藏掉（踩过）。逐项隐藏只靠上面的标题匹配。

    for (const cell of overlay.querySelectorAll('.ZCYAFq_navCell')) {
      const text = (cell.textContent || '').replace(/\s+/g, ' ').trim()
      cell.classList.toggle('wb-hidden', !KEEP_NAV.includes(text))
    }
    for (const actions of overlay.querySelectorAll('.ZCYAFq_actions')) {
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
    const center = document.querySelector('.OSewFq_centerCol')
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

  const boot = () => {
    attachStyle()
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
    setTimeout(bootDiag, 4600)
    // 自动探测只在调试时用：默认关闭，需要时控制台执行 __wbProbeSettings()
    if ((location.search + location.hash).includes('probe-settings')) setTimeout(probeSettings, 5200)
    setInterval(() => { sweep(); watchSettings() }, 2500)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot)
  } else {
    boot()
  }
})();
