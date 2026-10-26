/* ────────────────────────────────────────────────────────────────
 * 工作台 UI 注入脚本（改完刷新页面即生效；删掉本文件即完全恢复原样）
 *
 * 注意：这里跑在工作台页面的全局作用域，能做任意 DOM 操作。
 * 只在这里折腾工作台，别把东西写到安装目录。
 * ──────────────────────────────────────────────────────────────── */

;(() => {
  const LABEL = 'wb-ui'
  window.__WB_UI__ = {
    injected: true,
    at: new Date().toISOString(),
    label: LABEL,
    hidden: [],
  }
  console.info('[wb-ui] injected at', window.__WB_UI__.at)

  // ── 1) 自动关掉「预览版说明」弹窗（双保险）──────────────────────────
  // 首选方案：包补丁里写死 welcomeNoticeVersion（等价于点过「继续」）。
  // 这里兜一层：万一版本号变了 / 又弹出来，自动点掉那个「继续」按钮。
  const DISMISS_TEXTS = ['继续']
  const MAX_TRIES = 40
  let tries = 0

  const dismiss = () => {
    tries += 1
    if (tries > MAX_TRIES) return
    const buttons = Array.from(document.querySelectorAll('button'))
    const target = buttons.find((btn) => {
      const text = (btn.textContent || '').trim()
      if (!DISMISS_TEXTS.includes(text)) return false
      return Boolean(btn.closest('[role="dialog"], dialog, [class*="modal" i], [class*="dialog" i]'))
    })
    if (target && target.offsetParent !== null) {
      target.click()
      console.info('[wb-ui] dismissed preview notice')
    }
    if (tries < MAX_TRIES) setTimeout(dismiss, 500)
  }

  // ── 2) 隐藏工作台用不到的原版入口 ────────────────────────────────────
  // 只做“看不见”，不禁用插件——禁用一个提供服务的插件（如 ui-workspace 提供
  // uiWorkspace）会连带 11 个插件 pending，整页报 "entries did not activate"。
  const HIDE_TEXTS = ['插件', '自动化任务', '工作区', '默认工作区']

  const hideEntry = (el) => {
    if (!el || el.dataset.wbHidden === '1') return
    el.dataset.wbHidden = '1'
    el.style.display = 'none'
    window.__WB_UI__.hidden.push((el.textContent || '').trim().slice(0, 20))
  }

  const sweep = () => {
    const nodes = document.querySelectorAll('button, a, [role="button"], [role="listitem"], li, div')
    for (const node of nodes) {
      if (node.dataset.wbHidden === '1') continue
      const text = (node.textContent || '').trim()
      if (!text || text.length > 12) continue
      if (!HIDE_TEXTS.includes(text)) continue
      // 只在“侧栏/导航”的最小可点单元上动手，避免误伤正文
      const target = node.closest('button, a, [role="button"], [role="listitem"], li') || node
      hideEntry(target)
    }
    // 工作区区块标题下面紧跟着的会话/工作区行也一并隐藏
    for (const node of document.querySelectorAll('[data-wb-hidden="1"]')) {
      const parent = node.parentElement
      if (!parent) continue
      if ((node.textContent || '').trim() === '工作区') {
        for (const sibling of parent.querySelectorAll(':scope > *')) {
          const t = (sibling.textContent || '').trim()
          if (t && t.length < 24 && /工作区/.test(t)) hideEntry(sibling)
        }
      }
    }
  }

  const scheduleSweep = () => {
    sweep()
    // 单页应用会重绘，用 MutationObserver 循环补刀（节流 300ms）
    let pending = false
    const observer = new MutationObserver(() => {
      if (pending) return
      pending = true
      setTimeout(() => { pending = false; sweep() }, 300)
    })
    observer.observe(document.body, { childList: true, subtree: true })
  }

  const boot = () => {
    dismiss()
    scheduleSweep()
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot)
  } else {
    boot()
  }
})();
