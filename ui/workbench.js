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

  // ── 0) 基础样式 ─────────────────────────────────────────────────────
  const style = document.createElement('style')
  style.id = 'wb-ui-hide-style'
  style.textContent = `
    .wb-hidden { display: none !important; }
    #wb-topbar {
      position: fixed; top: 0; left: 0; right: 0; height: 46px;
      display: flex; align-items: center; gap: 6px; padding: 0 12px;
      background: var(--dsw-alias-bg-base, #16181d);
      border-bottom: 1px solid var(--dsw-alias-border-secondary, #2a2e37);
      z-index: 2147482000; box-sizing: border-box;
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
  const HIDE_TEXTS = ['插件', '自动化任务', '工作区', '默认工作区', '新会话']
  const SILENCE_TEXTS = ['新建会话失败', 'no agent factory', 'gateway/internal failed']

  const hide = (el) => {
    if (!el) return
    el.classList.add('wb-hidden')
    el.style.setProperty('display', 'none', 'important')
    const t = textOf(el).slice(0, 16)
    if (t && !state.hidden.includes(t)) state.hidden.push(t)
  }

  const sweep = () => {
    state.sweeps += 1
    attachStyle()
    for (const node of document.querySelectorAll('button, a, [role="button"], [role="listitem"], li, div, span')) {
      const text = textOf(node)
      if (!text || text.length > 24) continue
      if (HIDE_TEXTS.includes(text)) {
        hide(node.closest('button, a, [role="button"], [role="listitem"], li') || node)
        continue
      }
      if (SILENCE_TEXTS.some((n) => text.includes(n))) {
        hide(node.closest('[role="status"], [role="alert"], [class*="toast" i], [class*="alert" i]') || node)
      }
    }
    placeTopbar()
  }

  // ── 3) 把侧栏藏起来，换成顶部导航 ────────────────────────────────────
  const TABS = ['接口浏览器', '主驾会话', '设置']

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

  const clickTab = (text) => {
    const btn = findButton(text)
    if (btn) { btn.click(); markActive(text) }
  }

  const markActive = (text) => {
    const bar = document.getElementById('wb-topbar')
    if (!bar) return
    for (const tab of bar.querySelectorAll('button.wb-tab')) {
      tab.classList.toggle('wb-active', tab.dataset.wbTab === text)
    }
  }

  const buildTopbar = () => {
    if (document.getElementById('wb-topbar')) return document.getElementById('wb-topbar')
    const bar = document.createElement('div')
    bar.id = 'wb-topbar'
    const brand = document.createElement('div')
    brand.className = 'wb-brand'
    brand.innerHTML = 'DSH 工作台<small>59430</small>'
    bar.appendChild(brand)

    for (const text of TABS) {
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'wb-tab'
      btn.dataset.wbTab = text
      btn.textContent = text
      btn.addEventListener('click', () => clickTab(text))
      bar.appendChild(btn)
    }

    const spacer = document.createElement('div')
    spacer.className = 'wb-spacer'
    bar.appendChild(spacer)

    const dot = document.createElement('span')
    dot.className = 'wb-dot'
    dot.title = '工作台在线'
    bar.appendChild(dot)

    document.body.appendChild(bar)
    state.topbar = true
    return bar
  }

  // 让主内容区给顶栏留出高度
  const offsetMain = () => {
    const bar = document.getElementById('wb-topbar')
    if (!bar) return
    const h = bar.getBoundingClientRect().height || 46
    const chain = findSidebarChain()
    const outermost = chain.length ? chain[chain.length - 1] : null
    const main = outermost ? outermost.nextElementSibling : null
    const root = document.body.firstElementChild
    for (const el of [main, root].filter(Boolean)) {
      if (el.id === 'wb-topbar' || el.classList.contains('wb-hidden')) continue
      el.classList.add('wb-topbar-offset')
      el.style.setProperty('padding-top', `${h}px`, 'important')
    }
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
    offsetMain()
    if (!state.activeMarked && findButton('接口浏览器')) {
      state.activeMarked = true
      markActive('接口浏览器')
    }
  }

  // ── 4) 默认打开「接口浏览器」───────────────────────────────────────
  let defaulted = false
  const openDefault = () => {
    if (defaulted) return
    if (!/选择工作区|探索未至之境/.test(document.body ? document.body.innerText : '')) return
    const btn = findButton('接口浏览器')
    if (!btn) return
    defaulted = true
    btn.click()
    markActive('接口浏览器')
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

  const boot = () => {
    attachStyle()
    dismiss()
    sweep()
    observe()
    setTimeout(sweep, 300)
    setTimeout(sweep, 1200)
    setTimeout(() => { sweep(); openDefault() }, 900)
    setTimeout(() => { sweep(); openDefault() }, 2200)
    setInterval(() => { sweep(); offsetMain() }, 2000)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot)
  } else {
    boot()
  }
})();
