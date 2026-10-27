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
      noteWrap: { marginTop: 5, cursor: 'text' },
      noteText: { fontSize: 11.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55 },
      noteEmpty: { fontSize: 11, color: 'var(--dsw-alias-label-secondary)', opacity: 0.75 },
      noteEditor: {
        width: '100%',
        minHeight: 46,
        maxHeight: 160,
        resize: 'vertical',
        marginTop: 3,
        padding: '4px 6px',
        fontSize: 11.5,
        borderRadius: 6,
        border: '1px solid var(--dsw-alias-border-secondary)',
        background: 'var(--dsw-alias-bg-base)',
        color: 'var(--dsw-alias-label-primary)',
        font: 'inherit',
        boxSizing: 'border-box',
      },
      noteBtns: { display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 },
      noteBtn: {
        fontSize: 11,
        padding: '2px 8px',
        borderRadius: 6,
        border: '1px solid var(--dsw-alias-border-secondary)',
        background: 'transparent',
        color: 'var(--dsw-alias-label-primary)',
        cursor: 'pointer',
      },
      noteErr: { fontSize: 11, color: 'var(--dsw-alias-label-error, #d33)' },
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

    // 行构造：纯函数，页面调它，离线单测也调它（tools\test-plugin-notes.mjs）。
    // 插件行额外带 `note` 字段（空字符串=没有备注），没有 note 字段的行不是插件行。
    function buildRows(tab, data, needle) {
      const live = data.live
      const build = data.build
      const status = data.status
      const plugins = data.plugins
      const notes = data.notes || {}
      if (tab === 'plugins') {
        const list = (plugins && plugins.plugins) || []
        return list
          .filter((p) => {
            if (!needle) return true
            const note = notes[p.name] || ''
            return p.name.toLowerCase().includes(needle) || note.toLowerCase().includes(needle)
          })
          .map((p) => ({
            id: `plugin:${p.name}`,
            head: p.name,
            meta: [
              p.version ? `v${p.version}` : '无版本',
              p.inBundles ? '已登记' : '未登记',
              p.linked ? '已链接' : '缺 node_modules',
            ].join(' · '),
            body: `依赖声明: ${p.spec}`,
            note: notes[p.name] || '',
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
    }

    // 时间显示（面板上标数据来源用）
    function fmtWhen(iso) {
      if (!iso) return '?'
      const d = new Date(iso)
      if (Number.isNaN(d.getTime())) return '?'
      const pad = (n) => String(n).padStart(2, '0')
      return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
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
      const [notes, setNotes] = useState({})   // 插件备注：{ 包名: 备注文字 }
      const [editing, setEditing] = useState('') // 正在编辑备注的行 id
      const [draft, setDraft] = useState('')
      const [noteErr, setNoteErr] = useState('')
      const [refreshing, setRefreshing] = useState(false)

      // 拉一次所有数据（首屏与「刷新基线」共用）
      const loadAll = async () => {
        const [l, b, s, p, n] = await Promise.all([
          getJson('/wb-api/live').catch(() => null),
          getJson('/wb-api/build').catch(() => null),
          getJson('/wb-api/status').catch(() => null),
          getJson('/wb-api/plugins').catch(() => null),
          getJson('/wb-api/notes').then((r) => (r && r.notes) || {}).catch(() => ({})),
        ])
        setLive(l)
        setBuild(b)
        setStatus(s)
        setPlugins(p)
        setNotes(n || {})
        if (!l && !b && !s) setError('工作台还没有基线数据：点「刷新基线」重算')
      }

      // 「刷新基线」：重算 profile 分层（跑 dsh --dump-config），服务本来每次都是实时的
      const refreshBaseline = async () => {
        setRefreshing(true)
        setError('')
        try {
          const res = await fetch('/wb-api/refresh', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: '{}',
          })
          const body = await res.json().catch(() => ({}))
          if (!res.ok || body.ok === false) throw new Error(body.error || `HTTP ${res.status}`)
          await loadAll()
        } catch (e) {
          setError('刷新失败：' + String(e && e.message ? e.message : e))
        } finally {
          setRefreshing(false)
        }
      }

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
        loadAll()
          .catch((e) => { if (alive) setError(String(e && e.message ? e.message : e)) })
        return () => {
          alive = false
        }
      }, [])

      const needle = query.trim().toLowerCase()

      const rows = useMemo(
        () => buildRows(tab, { live, build, status, plugins, notes }, needle),
        [tab, live, build, status, plugins, notes, needle],
      )

      // 保存备注：空备注 = 删除这条
      const saveNote = async (name, text) => {
        setNoteErr('')
        try {
          const res = await fetch('/wb-api/notes', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ name, note: text }),
          })
          const body = await res.json().catch(() => ({}))
          if (!res.ok || body.ok === false) throw new Error(body.error || `HTTP ${res.status}`)
          setNotes(body.notes || {})
          setEditing('')
          setDraft('')
        } catch (e) {
          setNoteErr(String(e && e.message ? e.message : e))
        }
      }

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
          h(
            'button',
            {
              type: 'button',
              style: styles.chip,
              disabled: refreshing,
              title: '重算 profile 分层（跑一次 dsh --dump-config）；服务列表本来就是实时的',
              onClick: refreshBaseline,
            },
            refreshing ? '刷新中…' : '刷新基线',
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
                  // 插件备注：点一下就地编辑，Ctrl+Enter 保存，Esc 取消，清空即删除
                  r.note !== undefined
                    ? h(
                        'div',
                        {
                          style: styles.noteWrap,
                          title: r.note ? '点击编辑备注' : '点击给这个插件加备注',
                          onClick: (e) => {
                            e.stopPropagation()
                            if (editing === r.id) return
                            setEditing(r.id)
                            setDraft(r.note || '')
                            setNoteErr('')
                          },
                        },
                        editing === r.id
                          ? h(
                              'div',
                              null,
                              h('textarea', {
                                style: styles.noteEditor,
                                value: draft,
                                autoFocus: true,
                                placeholder: '这个插件是干嘛的、为什么装它…（Ctrl+Enter 保存，Esc 取消）',
                                onChange: (e) => setDraft(e.target.value),
                                onClick: (e) => e.stopPropagation(),
                                onKeyDown: (e) => {
                                  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                                    e.preventDefault()
                                    saveNote(r.head, draft)
                                  }
                                  if (e.key === 'Escape') {
                                    e.preventDefault()
                                    setEditing('')
                                    setDraft('')
                                  }
                                },
                              }),
                              h(
                                'div',
                                { style: styles.noteBtns },
                                h(
                                  'button',
                                  {
                                    type: 'button',
                                    style: styles.noteBtn,
                                    onClick: (e) => { e.stopPropagation(); saveNote(r.head, draft) },
                                  },
                                  '保存',
                                ),
                                h(
                                  'button',
                                  {
                                    type: 'button',
                                    style: styles.noteBtn,
                                    onClick: (e) => { e.stopPropagation(); setEditing(''); setDraft(''); setNoteErr('') },
                                  },
                                  '取消',
                                ),
                                noteErr ? h('span', { style: styles.noteErr }, noteErr) : null,
                              ),
                            )
                          : h('div', { style: r.note ? styles.noteText : styles.noteEmpty }, r.note || '＋ 加备注'),
                      )
                    : null,
                  expanded === r.id || needle
                    ? h('div', { style: { marginTop: 4 } }, r.body, r.extra ? h('div', { style: styles.dim }, r.extra) : null)
                    : null,
                ),
              ),
          h(
            'div',
            { style: styles.dim },
            `插件 ${counts.plugins}`
              + ` · 服务 ${counts.services}${live ? (live.servicesSource === 'live' ? '（实时）' : '（快照）') : ''}`
              + ` · 槽位 ${counts.slots}${live && live.slotsCollectedAt ? `（快照 ${fmtWhen(live.slotsCollectedAt)}）` : ''}`
              + ` · profile 行 ${counts.build}${build && build.generatedAt ? `（${fmtWhen(build.generatedAt)}）` : ''}`,
          ),
        ),
      )
    }

    return {
      inject: ['slots'],
      __test__: { buildRows },
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
