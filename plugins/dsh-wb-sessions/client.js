window.__ModuleLoader__.load({
  id: 'dsh-wb-sessions',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useRef, useMemo } = React

    const styles = {
      root: { display: 'flex', height: '100%', minHeight: 0, background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', font: 'inherit' },
      left: { width: 260, flex: '0 0 auto', borderRight: '1px solid var(--dsw-alias-border-secondary)', display: 'flex', flexDirection: 'column', minHeight: 0 },
      leftHead: { padding: '8px 10px', borderBottom: '1px solid var(--dsw-alias-border-secondary)', display: 'flex', gap: 6, alignItems: 'center' },
      title: { fontSize: 12, fontWeight: 600 },
      badge: { fontSize: 10, padding: '1px 6px', borderRadius: 8, background: 'var(--dsw-alias-bg-secondary)', color: 'var(--dsw-alias-label-secondary)' },
      list: { flex: 1, overflow: 'auto', minHeight: 0 },
      item: { padding: '7px 10px', borderBottom: '1px solid var(--dsw-alias-border-secondary)', cursor: 'pointer', fontSize: 12 },
      itemActive: { background: 'var(--dsw-alias-bg-secondary)' },
      itemSub: { color: 'var(--dsw-alias-label-secondary)', fontSize: 10, marginTop: 2 },
      right: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 },
      rightHead: { padding: '8px 10px', borderBottom: '1px solid var(--dsw-alias-border-secondary)', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center' },
      msgs: { flex: 1, overflow: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 },
      msg: { padding: '7px 9px', borderRadius: 8, fontSize: 12, whiteSpace: 'pre-wrap', lineHeight: 1.6, maxWidth: '92%' },
      user: { alignSelf: 'flex-end', background: 'var(--dsw-alias-bg-secondary)' },
      assistant: { alignSelf: 'flex-start', background: 'transparent', border: '1px solid var(--dsw-alias-border-secondary)' },
      meta: { fontSize: 10, color: 'var(--dsw-alias-label-secondary)', marginBottom: 3 },
      composer: { borderTop: '1px solid var(--dsw-alias-border-secondary)', padding: 8, display: 'flex', gap: 6, alignItems: 'flex-end' },
      textarea: { flex: 1, minHeight: 54, maxHeight: 160, resize: 'vertical', padding: '6px 8px', fontSize: 12, borderRadius: 6, border: '1px solid var(--dsw-alias-border-secondary)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', font: 'inherit' },
      btn: { padding: '6px 12px', fontSize: 12, borderRadius: 6, border: '1px solid var(--dsw-alias-border-secondary)', background: 'var(--dsw-alias-bg-secondary)', color: 'var(--dsw-alias-label-primary)', cursor: 'pointer' },
      notice: { padding: 14, fontSize: 12, color: 'var(--dsw-alias-label-secondary)' },
      err: { padding: '6px 10px', fontSize: 11, color: 'var(--dsw-alias-label-error, #d33)' },
      warn: { padding: '4px 10px', fontSize: 10, color: 'var(--dsw-alias-label-secondary)' },
    }

    async function jsonFetch(path, init) {
      const res = await fetch(path, { headers: { accept: 'application/json' }, ...(init || {}) })
      const body = await res.json().catch(() => ({}))
      if (!res.ok || body.ok === false) throw new Error(body.error || `HTTP ${res.status}`)
      return body
    }

    function fmtTime(ms) {
      if (!ms) return ''
      const d = new Date(Number(ms))
      if (Number.isNaN(d.getTime())) return ''
      const diff = Date.now() - d.getTime()
      if (diff >= 0 && diff < 60000) return '刚刚'
      if (diff >= 0 && diff < 3600000) return `${Math.round(diff / 60000)} 分钟前`
      const pad = (n) => String(n).padStart(2, '0')
      return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    }

    function Icon() {
      return h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8 },
        h('path', { d: 'M4 5h16v11H8l-4 3z' }))
    }

    function Panel() {
      const [sessions, setSessions] = useState([])
      const [selected, setSelected] = useState('')
      const [messages, setMessages] = useState([])
      const [draft, setDraft] = useState('')
      const [mode, setMode] = useState('queue')
      const [error, setError] = useState('')
      const [busy, setBusy] = useState(false)
      const [hasToken, setHasToken] = useState(true)
      const listTimer = useRef(0)

      const loadList = async () => {
        try {
          const body = await jsonFetch('/wb-sessions/list')
          setSessions(body.items || [])
          setError('')
        } catch (e) {
          setError(String(e.message || e))
        }
      }

      const loadPage = async (id) => {
        if (!id) return
        try {
          const body = await jsonFetch(`/wb-sessions/page?id=${encodeURIComponent(id)}&max=50`)
          setMessages(body.messages || [])
          setError('')
        } catch (e) {
          setError(String(e.message || e))
        }
      }

      useEffect(() => {
        ;(async () => {
          try {
            const health = await jsonFetch('/wb-sessions/health')
            setHasToken(Boolean(health.hasToken))
          } catch { /* 忽略 */ }
          await loadList()
        })()
        listTimer.current = setInterval(loadList, 10000)
        return () => clearInterval(listTimer.current)
      }, [])

      useEffect(() => { if (selected) loadPage(selected) }, [selected])

      const send = async () => {
        const text = draft.trim()
        if (!text || !selected || busy) return
        setBusy(true)
        try {
          await jsonFetch('/wb-sessions/send', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ sessionId: selected, text, mode }),
          })
          setDraft('')
          setTimeout(() => loadPage(selected), 600)
        } catch (e) {
          setError(String(e.message || e))
        } finally {
          setBusy(false)
        }
      }

      const rows = useMemo(() => sessions, [sessions])
      const current = rows.find((s) => s.sessionId === selected)

      return h('div', { style: styles.root },
        h('div', { style: styles.left },
          h('div', { style: styles.leftHead },
            h('span', { style: styles.title }, '主驾会话'),
            h('span', { style: styles.badge }, `${rows.length}`),
            h('button', { type: 'button', style: { ...styles.btn, marginLeft: 'auto', padding: '2px 8px', fontSize: 11 }, onClick: loadList }, '刷新'),
          ),
          h('div', { style: styles.list },
            rows.length === 0
              ? h('div', { style: styles.notice }, '没有会话（主驾没开或还没会话）')
              : rows.map((s) => h('div', {
                  key: s.sessionId,
                  style: s.sessionId === selected ? { ...styles.item, ...styles.itemActive } : styles.item,
                  onClick: () => setSelected(s.sessionId),
                },
                h('div', null, (s.cwd || '').split(/[\\/]/).filter(Boolean).slice(-1)[0] || '会话',
                  s.running ? h('span', { style: { ...styles.badge, marginLeft: 6 } }, '运行中') : null),
                h('div', { style: styles.itemSub }, `${s.sessionId.slice(0, 18)}… · ${fmtTime(s.updatedAt)}`),
              )),
          ),
        ),
        h('div', { style: styles.right },
          h('div', { style: styles.rightHead },
            h('span', { style: styles.title }, current ? (current.sessionId.slice(0, 24) + '…') : '选一个会话'),
            current ? h('span', { style: styles.badge }, current.cwd || '') : null,
            h('button', { type: 'button', style: { ...styles.btn, marginLeft: 'auto', padding: '2px 8px', fontSize: 11 }, onClick: () => loadPage(selected) }, '读取历史'),
          ),
          hasToken ? null : h('div', { style: styles.warn }, '主驾桥还没启用会话接口：重启一次主程序即可。'),
          error ? h('div', { style: styles.err }, error) : null,
          h('div', { style: styles.msgs },
            messages.length === 0
              ? h('div', { style: styles.notice }, selected ? '这个会话还没有可显示的消息' : '左边选一个会话看历史')
              : messages.map((m) => h('div', {
                  key: `${m.seq}`,
                  style: m.role === 'user' ? { ...styles.msg, ...styles.user } : { ...styles.msg, ...styles.assistant },
                },
                h('div', { style: styles.meta }, `${m.role || m.type} · #${m.seq} · ${fmtTime(m.time)}`),
                m.text,
              )),
          ),
          h('div', { style: styles.composer },
            h('textarea', {
              style: styles.textarea,
              placeholder: selected ? '发到这个会话（会作为主驾那边的用户消息，触发它开始运行）' : '先选一个会话',
              value: draft,
              disabled: !selected,
              onChange: (e) => setDraft(e.target.value),
            }),
            h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
              h('select', { value: mode, onChange: (e) => setMode(e.target.value), style: { ...styles.btn, padding: '2px 6px' } },
                h('option', { value: 'queue' }, '排队'),
                h('option', { value: 'steer' }, '插入'),
              ),
              h('button', { type: 'button', style: styles.btn, disabled: !selected || busy, onClick: send }, busy ? '发送中…' : '发送'),
            ),
          ),
        ),
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register({ name: 'sidebar.panellist', id: 'wb-sessions', order: 45, label: () => '主驾会话' }, Icon))
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: 'wb-sessions' }, Panel))
      },
    }
  },
})
