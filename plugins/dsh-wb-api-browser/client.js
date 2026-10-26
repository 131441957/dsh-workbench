window.__ModuleLoader__.load({
  id: 'dsh-wb-api-browser',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useMemo } = React

    // 「插件」已拆成独立面板（顶栏/侧栏入口 wb-plugins），这里只放状态类标签
    const TABS = [
      { id: 'services', label: '宿主服务' },
      { id: 'slots', label: '前端槽位' },
      { id: 'build', label: 'profile 分层' },
      { id: 'status', label: '主驾状态' },
    ]

    const styles = {
      root: {
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
        background: 'var(--dsw-alias-bg-base)',
        color: 'var(--dsw-alias-label-primary)',
        font: 'inherit',
      },
      header: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '10px 12px',
        borderBottom: '1px solid var(--dsw-alias-border-secondary)',
        flexWrap: 'wrap',
      },
      title: { fontSize: 13, fontWeight: 600 },
      badge: {
        fontSize: 10,
        padding: '1px 6px',
        borderRadius: 8,
        background: 'var(--dsw-alias-bg-secondary)',
        color: 'var(--dsw-alias-label-secondary)',
      },
      chip: {
        fontSize: 11,
        padding: '3px 8px',
        borderRadius: 10,
        border: '1px solid var(--dsw-alias-border-secondary)',
        background: 'transparent',
        color: 'var(--dsw-alias-label-secondary)',
        cursor: 'pointer',
      },
      chipActive: {
        background: 'var(--dsw-alias-bg-secondary)',
        color: 'var(--dsw-alias-label-primary)',
      },
      search: {
        marginLeft: 'auto',
        minWidth: 160,
        padding: '4px 8px',
        fontSize: 12,
        borderRadius: 6,
        border: '1px solid var(--dsw-alias-border-secondary)',
        background: 'var(--dsw-alias-bg-base)',
        color: 'var(--dsw-alias-label-primary)',
      },
      list: { flex: 1, overflow: 'auto', padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 6 },
      row: {
        padding: '6px 8px',
        borderRadius: 6,
        background: 'var(--dsw-alias-bg-secondary)',
        fontSize: 12,
        lineHeight: 1.5,
      },
      key: { fontFamily: 'ui-monospace, Consolas, monospace', fontWeight: 600 },
      dim: { color: 'var(--dsw-alias-label-secondary)', fontSize: 11 },
      notice: { padding: 16, fontSize: 12, color: 'var(--dsw-alias-label-secondary)' },
      err: { padding: 12, fontSize: 12, color: 'var(--dsw-alias-label-error, #d33)' },
    }

    async function getJson(path) {
      const res = await fetch(path, { headers: { accept: 'application/json' } })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.json()
    }

    function Icon() {
      return h(
        'svg',
        { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8 },
        h('rect', { x: 3, y: 4, width: 18, height: 6, rx: 2 }),
        h('rect', { x: 3, y: 14, width: 8, height: 6, rx: 2 }),
        h('rect', { x: 14, y: 14, width: 7, height: 6, rx: 2 }),
      )
    }

    function Panel(props) {
      const fixedTab = props && props.fixedTab
      const hideTabs = Boolean(props && props.hideTabs)
      const [tab, setTab] = useState(fixedTab || 'services')
      const [live, setLive] = useState(null)
      const [build, setBuild] = useState(null)
      const [status, setStatus] = useState(null)
      const [plugins, setPlugins] = useState(null)
      const [error, setError] = useState('')
      const [query, setQuery] = useState('')
      const [expanded, setExpanded] = useState('')

      useEffect(() => {
        // 允许外部（顶栏）切到指定标签页：window.__wbApiSelect('plugins')
        const select = (id) => {
          if (!fixedTab && ['plugins', 'services', 'slots', 'build', 'status'].includes(id)) setTab(id)
        }
        window.__wbApiSelect = select
        const onEvent = (event) => select(event && event.detail)
        window.addEventListener('wb:select-tab', onEvent)
        return () => {
          window.removeEventListener('wb:select-tab', onEvent)
          if (window.__wbApiSelect === select) delete window.__wbApiSelect
        }
      }, [])

      useEffect(() => {
        let alive = true
        ;(async () => {
          try {
            const [l, b, s, p] = await Promise.all([
              getJson('/wb-api/live').catch(() => null),
              getJson('/wb-api/build').catch(() => null),
              getJson('/wb-api/status').catch(() => null),
              getJson('/wb-api/plugins').catch(() => null),
            ])
            if (!alive) return
            setLive(l)
            setBuild(b)
            setStatus(s)
            setPlugins(p)
            if (!l && !b && !s) setError('工作台还没有基线数据：先跑 wb.py api')
          } catch (e) {
            if (alive) setError(String(e && e.message ? e.message : e))
          }
        })()
        return () => {
          alive = false
        }
      }, [])

      const needle = query.trim().toLowerCase()

      const rows = useMemo(() => {
        if (tab === 'plugins') {
          const list = (plugins && plugins.plugins) || []
          return list
            .filter((p) => !needle || p.name.toLowerCase().includes(needle))
            .map((p) => ({
              id: `plugin:${p.name}`,
              head: p.name,
              meta: [
                p.version ? `v${p.version}` : '无版本',
                p.inBundles ? '已登记' : '未登记',
                p.linked ? '已链接' : '缺 node_modules',
              ].join(' · '),
              body: `依赖声明: ${p.spec}`,
              extra: !p.inBundles || !p.linked ? '⚠️ 这条不会生效：' + (!p.inBundles ? '没加进 bundles；' : '') + (!p.linked ? 'node_modules 里找不到；' : '') : '',
            }))
        }
        if (tab === 'services') {
          const list = (live && live.services) || []
          return list
            .filter((s) => !needle || s.key.toLowerCase().includes(needle) || (s.description || '').toLowerCase().includes(needle))
            .map((s) => ({
              id: s.key,
              head: s.key,
              meta: `${s.methodCount} 个方法`,
              body: s.description || '',
            }))
        }
        if (tab === 'slots') {
          const list = (live && live.slots) || []
          return list
            .filter((s) => !needle || s.name.toLowerCase().includes(needle) || (s.purpose || '').toLowerCase().includes(needle))
            .map((s) => ({
              id: s.name,
              head: s.name,
              meta: `${s.kind} · ${s.scope}`,
              body: s.purpose || '',
              extra: s.taken && s.taken.length ? `已被占用: ${s.taken.slice(0, 6).join(', ')}` : '',
            }))
        }
        if (tab === 'build') {
          const layers = (build && build.layers) || []
          return layers.map((l) => ({
            id: l.layer,
            head: l.layer,
            meta: `${l.rows.length} 行`,
            body: l.rows.map((r) => (r.disabled ? `~~${r.id}~~` : r.id)).join(', '),
          }))
        }
        if (!status) return []
        const m = status.memory || {}
        return [
          { id: 'ports', head: '主驾端口', meta: '', body: JSON.stringify((status.mainHarness || {}).ports || []) },
          { id: 'memory', head: '记忆条数', meta: '', body: Object.entries(m).map(([k, v]) => `${k}=${v}`).join(' / ') },
          { id: 'collected', head: '快照时间', meta: '', body: status.collectedAt || '' },
        ]
      }, [tab, live, build, status, needle])

      const counts = {
        plugins: (plugins && plugins.plugins && plugins.plugins.length) || 0,
        services: (live && live.counts && live.counts.services) || 0,
        slots: (live && live.counts && live.counts.slots) || 0,
        build: (build && build.totals && build.totals.rows) || 0,
      }

      return h(
        'div',
        { style: styles.root, 'data-wb-panel': 'api-browser' },
        h(
          'div',
          { style: styles.header },
          h('span', { style: styles.title }, fixedTab === 'plugins' ? '工作台插件' : '工作台状态 v2'),
          h('span', { style: styles.badge }, live ? `DSH ${live.version}` : '未采集'),
          hideTabs
            ? null
            : TABS.map((t) =>
                h(
                  'button',
                  {
                    key: t.id,
                    type: 'button',
                    style: tab === t.id ? { ...styles.chip, ...styles.chipActive } : styles.chip,
                    onClick: () => setTab(t.id),
                  },
                  t.label,
                ),
              ),
          h('input', {
            style: styles.search,
            placeholder: '过滤…',
            value: query,
            onChange: (e) => setQuery(e.target.value),
          }),
        ),
        error ? h('div', { style: styles.err }, error) : null,
        h(
          'div',
          { style: styles.list },
          rows.length === 0
            ? h('div', { style: styles.notice }, '没有匹配项')
            : rows.map((r) =>
                h(
                  'div',
                  {
                    key: r.id,
                    style: { ...styles.row, cursor: 'pointer' },
                    onClick: () => setExpanded(expanded === r.id ? '' : r.id),
                  },
                  h(
                    'div',
                    { style: { display: 'flex', gap: 8, alignItems: 'baseline' } },
                    h('span', { style: styles.key }, r.head),
                    r.meta ? h('span', { style: styles.dim }, r.meta) : null,
                  ),
                  expanded === r.id || needle
                    ? h('div', { style: { marginTop: 4 } }, r.body, r.extra ? h('div', { style: styles.dim }, r.extra) : null)
                    : null,
                ),
              ),
          h(
            'div',
            { style: styles.dim },
            `插件 ${counts.plugins} · 服务 ${counts.services} · 槽位 ${counts.slots} · profile 行 ${counts.build}`,
          ),
        ),
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            { name: 'sidebar.panellist', id: 'wb-api', order: 40, label: () => '状态' },
            Icon,
          ),
        )
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: 'wb-api' }, Panel))
        // 插件清单单独成一个面板（顶栏「插件」指向它），不与「状态」重复
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            { name: 'sidebar.panellist', id: 'wb-plugins', order: 41, label: () => '插件' },
            Icon,
          ),
        )
        ctx.slots.inject('main', () =>
          ctx.slots.register({ name: 'main', key: 'wb-plugins' }, () => h(Panel, { fixedTab: 'plugins', hideTabs: true })),
        )
      },
    }
  },
})
