/* ────────────────────────────────────────────────────────────────
 * 工作台 UI 注入脚本（改完刷新页面即生效；删掉本文件即完全恢复原样）
 *
 * 注意：这里跑在工作台页面的全局作用域，能做任意 DOM 操作。
 * 只在这里折腾工作台，别把东西写到安装目录。
 * ──────────────────────────────────────────────────────────────── */

;(() => {
  const LABEL = 'wb-ui'
  const state = { hidden: [], sweeps: 0, dismissed: 0 }
  window.__WB_UI__ = state
  window.__wbSweep = () => sweep()
  console.info('[wb-ui] injected')

  // ── 一个 !important 的隐藏类：React 重绘会冲掉内联 style，但每次 swept 都会补
  const style = document.createElement('style')
  style.id = 'wb-ui-hide-style'
  style.textContent = '.wb-hidden{display:none!important}'
  const attachStyle = () => {
    if (!document.head.contains(style)) document.head.appendChild(style)
  }

  // ── 1) 自动关掉「预览版说明」弹窗 ────────────────────────────────────
  const DISMISS_TEXTS = ['继续']
  let tries = 0
  const dismiss = () => {
    tries += 1
    if (tries > 40) return
    const buttons = Array.from(document.querySelectorAll('button'))
    const target = buttons.find((btn) => {
      const text = (btn.textContent || '').replace(/\s+/g, '').trim()
      if (!DISMISS_TEXTS.includes(text)) return false
      return Boolean(btn.closest('[role="dialog"], dialog, [class*="modal" i], [class*="dialog" i]'))
    })
    if (target && target.offsetParent !== null) {
      target.click()
      state.dismissed += 1
    }
    setTimeout(dismiss, 500)
  }

  // ── 2) 隐藏工作台用不到的原版入口（只隐藏，不禁用插件）────────────────
  // 禁用「提供服务」的插件会让其它插件 pending（例如 ui-workspace 提供 uiWorkspace）。
  const HIDE_TEXTS = ['插件', '自动化任务', '工作区', '默认工作区', '新会话']
  // 应用在没有 agent 时自己会尝试新建会话并弹一个错误 toast，一并压掉
  const SILENCE_TEXTS = ['新建会话失败', 'no agent factory', 'gateway/internal failed']

  const textOf = (el) => (el.textContent || '').replace(/\s+/g, '').trim()

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
    const nodes = document.querySelectorAll('button, a, [role="button"], [role="listitem"], li, div, span')
    for (const node of nodes) {
      if (node.closest('#wb-ui-hide-style')) continue
      const text = textOf(node)
      if (!text || text.length > 24) continue
      if (HIDE_TEXTS.includes(text)) {
        hide(node.closest('button, a, [role="button"], [role="listitem"], li') || node)
        continue
      }
      if (SILENCE_TEXTS.some((needle) => text.includes(needle))) {
        // toast 一般是个浮层：往上找到定位容器再隐藏
        hide(node.closest('[role="status"], [role="alert"], [class*="toast" i], [class*="alert" i]') || node)
      }
    }
  }

  const observe = () => {
    let pending = false
    const observer = new MutationObserver(() => {
      if (pending) return
      pending = true
      setTimeout(() => { pending = false; sweep() }, 200)
    })
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] })
  }

  // ── 3) 默认打开「接口浏览器」，别停在没用的会话空状态 ────────────────
  const DEFAULT_PANEL = '接口浏览器'
  let defaulted = false
  const isConversationLanding = () => /选择工作区|探索未至之境/.test(document.body ? document.body.innerText : '')
  const openDefaultPanel = () => {
    if (defaulted) return
    if (!isConversationLanding()) return
    const entry = Array.from(document.querySelectorAll('button, a, [role="button"]'))
      .find((el) => textOf(el) === DEFAULT_PANEL)
    if (!entry) return
    defaulted = true
    entry.click()
  }

  const boot = () => {
    attachStyle()
    dismiss()
    sweep()
    observe()
    setTimeout(sweep, 300)
    setTimeout(sweep, 1200)
    setTimeout(() => { sweep(); openDefaultPanel() }, 800)
    setTimeout(() => { sweep(); openDefaultPanel() }, 2000)
    setInterval(sweep, 2000)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot)
  } else {
    boot()
  }
})();
