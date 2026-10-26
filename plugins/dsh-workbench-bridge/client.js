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
