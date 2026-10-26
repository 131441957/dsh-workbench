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
  }
  console.info('[wb-ui] injected at', window.__WB_UI__.at)

  // ── 自动关掉「预览版说明」弹窗（双保险）────────────────────────────
  // 首选方案：把 welcomeNoticeVersion 写进 profile 配置（等价于点过「继续」）。
  // 这里再兜一层：万一版本号变了 / 又弹出来，脚本自动点掉那个「继续」按钮。
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
      // 只在“确实有对话框”的时候点，避免误点普通按钮
      return Boolean(btn.closest('[role="dialog"], dialog, [class*="modal" i], [class*="dialog" i]'))
    })
    if (target && target.offsetParent !== null) {
      target.click()
      console.info('[wb-ui] dismissed preview notice')
    }
    if (tries < MAX_TRIES) setTimeout(dismiss, 500)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', dismiss)
  } else {
    dismiss()
  }
})();
