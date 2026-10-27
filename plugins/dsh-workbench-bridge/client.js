/* ══════════════════════════════════════════════════════════════════════════
 * dsh-workbench-bridge —— 客户端半（主驾界面里的「工作台」状态徽章）
 * --------------------------------------------------------------------------
 * 注意：这是**装在主 harness 上的插件**，用户的主界面里能看到它。它只做展示 +
 * 一个跳转入口，不注册任何面板，也不碰主驾的会话/设置。
 *
 * 数据来自主驾自己的 /wb-bridge/status（同源请求，不需要 token：该路由是公开只读）。
 * 工作台没起来时显示灰点，起来了显示绿点 + 延迟。
 *
 * 改完怎么验证：主程序重启后（宿主侧改动必须重启）看主界面顶部状态徽章是否变绿；
 *               或用 python tools\test-http.py --bridge 验 /wb-bridge/status。
 * ══════════════════════════════════════════════════════════════════════════ */
window.__ModuleLoader__.load({
  id: 'dsh-workbench-bridge',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect } = React

    const styles = {
      btn: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 8px',
        borderRadius: 8,
        border: '1px solid var(--dsw-alias-border-secondary)',
        background: 'transparent',
        color: 'var(--dsw-alias-label-secondary)',
        fontSize: 11,
        cursor: 'pointer',
        font: 'inherit',
      },
      dot: { width: 7, height: 7, borderRadius: '50%', background: '#999', flex: '0 0 auto' },
      dotOn: { background: '#2ecc71', boxShadow: '0 0 4px #2ecc71' },
      dotOff: { background: '#e74c3c' },
    }

    function WorkbenchStatus() {
      const [state, setState] = useState({ loading: true })
      const [tip, setTip] = useState('')

      useEffect(() => {
        let alive = true
        const tick = async () => {
          try {
            const res = await fetch('/wb-bridge/status', { headers: { accept: 'application/json' } })
            const body = await res.json()
            if (!alive) return
            setState({ loading: false, ...(body.workbench || {}) })
          } catch (error) {
            if (alive) setState({ loading: false, reachable: false, reason: String(error) })
          }
        }
        tick()
        const timer = setInterval(tick, 5000)
        return () => {
          alive = false
          clearInterval(timer)
        }
      }, [])

      const on = Boolean(state.reachable)
      const label = state.loading ? '工作台…' : on ? `工作台 ${state.port}` : '工作台未接入'
      const detail = on
        ? `DSH ${state.version || '?'} · 服务 ${state.services ?? '?'} · 槽位 ${state.slots ?? '?'} · 快照 ${state.snapshotAt || '未采集'}`
        : state.reason || '端口不可达'

      return h(
        'button',
        {
          type: 'button',
          style: styles.btn,
          title: detail,
          onMouseEnter: () => setTip(detail),
          onMouseLeave: () => setTip(''),
          onClick: () => setTip(detail),
        },
        h('span', { style: { ...styles.dot, ...(state.loading ? {} : on ? styles.dotOn : styles.dotOff) } }),
        h('span', null, label),
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('sidebar.footer.action', () =>
          ctx.slots.register(
            { name: 'sidebar.footer.action', id: 'wb-bridge', order: 20, label: () => '工作台' },
            WorkbenchStatus,
          ),
        )
      },
    }
  },
})
