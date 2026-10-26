window.__ModuleLoader__.load({
  id: 'dsh-wb-sessions',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useRef, useMemo } = React

    // ── 极简 Markdown 渲染（不引三方库，只支持聊天里常见的语法）──────────
    function inlineNodes(text, keyPrefix) {
      const nodes = []
      const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))|(https?:\/\/[^\s)]+)/
      let rest = text
      let index = 0
      let safety = 0
      while (rest.length && safety < 500) {
        safety += 1
        const match = pattern.exec(rest)
        if (!match) {
          nodes.push(rest)
          break
        }
        if (match.index > 0) nodes.push(rest.slice(0, match.index))
        const token = match[0]
        const key = `${keyPrefix}-${index++}`
        if (token.startsWith('`')) {
          nodes.push(h('code', { key, style: md.inlineCode }, token.slice(1, -1)))
        } else if (token.startsWith('**')) {
          nodes.push(h('strong', { key }, token.slice(2, -2)))
        } else if (token.startsWith('*')) {
          nodes.push(h('em', { key }, token.slice(1, -1)))
        } else if (token.startsWith('[')) {
          const m = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token)
          if (m) nodes.push(h('a', { key, href: m[2], target: '_blank', rel: 'noreferrer', style: md.link }, m[1]))
          else nodes.push(token)
        } else if (token.startsWith('http')) {
          nodes.push(h('a', { key, href: token, target: '_blank', rel: 'noreferrer', style: md.link }, token))
        }
        rest = rest.slice(match.index + token.length)
      }
      return nodes
    }

    const md = {
      p: { margin: '4px 0', lineHeight: 1.65 },
      h1: { fontSize: 15, margin: '10px 0 4px', fontWeight: 700 },
      h2: { fontSize: 14, margin: '10px 0 4px', fontWeight: 700 },
      h3: { fontSize: 13, margin: '8px 0 3px', fontWeight: 700 },
      h4: { fontSize: 12.5, margin: '8px 0 3px', fontWeight: 700 },
      code: { background: 'var(--dsw-alias-bg-secondary)', padding: '1px 5px', borderRadius: 4, fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 11.5 },
      inlineCode: { background: 'var(--dsw-alias-bg-secondary)', padding: '1px 5px', borderRadius: 4, fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 11.5 },
      pre: { background: 'var(--dsw-alias-bg-secondary)', padding: '8px 10px', borderRadius: 6, overflowX: 'auto', margin: '6px 0', fontSize: 11.5, lineHeight: 1.55 },
      ul: { margin: '4px 0', paddingLeft: 20 },
      ol: { margin: '4px 0', paddingLeft: 20 },
      li: { margin: '2px 0', lineHeight: 1.6 },
      quote: { borderLeft: '3px solid var(--dsw-alias-border-secondary)', margin: '6px 0', padding: '2px 0 2px 10px', color: 'var(--dsw-alias-label-secondary)' },
      hr: { border: 'none', borderTop: '1px solid var(--dsw-alias-border-secondary)', margin: '10px 0' },
      link: { color: 'var(--dsw-alias-label-link, #3b82f6)', textDecoration: 'underline' },
      table: { borderCollapse: 'collapse', margin: '6px 0', fontSize: 11.5 },
      th: { border: '1px solid var(--dsw-alias-border-secondary)', padding: '3px 8px', background: 'var(--dsw-alias-bg-secondary)', textAlign: 'left' },
      td: { border: '1px solid var(--dsw-alias-border-secondary)', padding: '3px 8px' },
    }

    function renderMarkdown(text) {
      const lines = String(text).replace(/\r\n/g, '\n').split('\n')
      const blocks = []
      let i = 0
      let key = 0
      const isSpecial = (line) =>
        /^```/.test(line) || /^#{1,6}\s/.test(line) || /^\s*[-*]\s+/.test(line) ||
        /^\s*\d+\.\s+/.test(line) || /^>\s?/.test(line) || /^\|.*\|/.test(line) || /^\s*---+\s*$/.test(line)

      while (i < lines.length) {
        const line = lines[i]
        if (!line.trim()) { i += 1; continue }

        if (/^```/.test(line)) {
          const lang = line.slice(3).trim()
          const buf = []
          i += 1
          while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i += 1 }
          i += 1
          blocks.push(h('pre', { key: `b${key++}`, style: md.pre },
            h('code', { style: { fontFamily: 'inherit' } }, buf.join('\n'))))
          if (lang) { /* 语言标记先忽略，不做高亮 */ }
          continue
        }

        const heading = /^(#{1,6})\s+(.*)$/.exec(line)
        if (heading) {
          const level = Math.min(heading[1].length, 4)
          const style = md[`h${level}`]
          blocks.push(h(`h${level}`, { key: `b${key++}`, style }, inlineNodes(heading[2], `h${key}`)))
          i += 1
          continue
        }

        if (/^\s*---+\s*$/.test(line)) { blocks.push(h('hr', { key: `b${key++}`, style: md.hr })); i += 1; continue }

        if (/^\|.*\|/.test(line)) {
          const rows = []
          while (i < lines.length && /^\|.*\|/.test(lines[i])) { rows.push(lines[i]); i += 1 }
          const cells = rows.map((r) => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim()))
          const isSep = (arr) => arr.every((c) => /^:?-{2,}:?$/.test(c))
          const body = cells.filter((arr) => !isSep(arr))
          if (body.length) {
            const [head, ...rest] = body
            blocks.push(h('table', { key: `b${key++}`, style: md.table },
              h('thead', null, h('tr', null, head.map((c, ci) => h('th', { key: ci, style: md.th }, inlineNodes(c, `th${ci}`))))),
              h('tbody', null, rest.map((row, ri) => h('tr', { key: ri },
                row.map((c, ci) => h('td', { key: ci, style: md.td }, inlineNodes(c, `td${ri}-${ci}`))))))))
          }
          continue
        }

        if (/^\s*[-*]\s+/.test(line)) {
          const items = []
          while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
            items.push(lines[i].replace(/^\s*[-*]\s+/, ''))
            i += 1
          }
          blocks.push(h('ul', { key: `b${key++}`, style: md.ul },
            items.map((it, ii) => h('li', { key: ii, style: md.li }, inlineNodes(it, `li${ii}`)))))
          continue
        }

        if (/^\s*\d+\.\s+/.test(line)) {
          const items = []
          while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
            items.push(lines[i].replace(/^\s*\d+\.\s+/, ''))
            i += 1
          }
          blocks.push(h('ol', { key: `b${key++}`, style: md.ol },
            items.map((it, ii) => h('li', { key: ii, style: md.li }, inlineNodes(it, `oli${ii}`)))))
          continue
        }

        if (/^>\s?/.test(line)) {
          const buf = []
          while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i += 1 }
          blocks.push(h('div', { key: `b${key++}`, style: md.quote }, inlineNodes(buf.join('\n'), `q${key}`)))
          continue
        }

        // 普通段落：吃到空行或下一个特殊行
        const buf = [line]
        i += 1
        while (i < lines.length && lines[i].trim() && !isSpecial(lines[i])) { buf.push(lines[i]); i += 1 }
        blocks.push(h('p', { key: `b${key++}`, style: md.p }, inlineNodes(buf.join('\n'), `p${key}`)))
      }
      return blocks
    }

    // ── 样式 ────────────────────────────────────────────────────────────
    const styles = {
      root: { display: 'flex', height: '100%', minHeight: 0, background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', font: 'inherit' },
      left: { width: 290, flex: '0 0 auto', borderRight: '1px solid var(--dsw-alias-border-secondary)', display: 'flex', flexDirection: 'column', minHeight: 0 },
      leftHead: { padding: '8px 10px', borderBottom: '1px solid var(--dsw-alias-border-secondary)', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'nowrap', minWidth: 0 },
      liveRow: { padding: '5px 10px 6px', fontSize: 10, color: 'var(--dsw-alias-label-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', borderBottom: '1px solid var(--dsw-alias-border-secondary)' },
      title: { fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0, flex: '0 1 auto' },
      badge: { fontSize: 10, padding: '1px 6px', borderRadius: 8, background: 'var(--dsw-alias-bg-secondary)', color: 'var(--dsw-alias-label-secondary)', flex: '0 0 auto' },
      list: { flex: 1, overflow: 'auto', minHeight: 0 },
      item: { padding: '7px 10px', borderBottom: '1px solid var(--dsw-alias-border-secondary)', cursor: 'pointer', fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
      itemActive: { background: 'var(--dsw-alias-bg-secondary)' },
      itemSub: { color: 'var(--dsw-alias-label-secondary)', fontSize: 10, marginTop: 2 },
      right: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 },
      rightHead: { padding: '8px 10px', borderBottom: '1px solid var(--dsw-alias-border-secondary)', fontSize: 12, display: 'flex', gap: 8, alignItems: 'center' },
      msgs: { flex: 1, overflow: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 0, minHeight: 0 },
      row: { display: 'flex', flexDirection: 'column', gap: 3, maxWidth: '100%', paddingTop: 12 },
      rowFirst: { paddingTop: 0 },
      rowDivider: { borderTop: '1px solid var(--dsw-alias-border-secondary)' },
      rowUser: { alignItems: 'flex-end' },
      rowOther: { alignItems: 'flex-start' },
      meta: { fontSize: 10, color: 'var(--dsw-alias-label-secondary)', opacity: 0.75 },
      bubble: { maxWidth: '86%', padding: '9px 12px', borderRadius: 10, fontSize: 12.5, minWidth: 0, overflowWrap: 'anywhere' },
      bubbleUser: {
        background: 'rgba(64, 132, 255, 0.16)',
        border: '1px solid rgba(64, 132, 255, 0.45)',
      },
      bubbleAssistant: { background: 'transparent', border: '1px solid var(--dsw-alias-border-secondary)' },
      more: { marginTop: 4, fontSize: 11, color: 'var(--dsw-alias-label-link, #3b82f6)', cursor: 'pointer', background: 'none', border: 'none', padding: 0 },
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

    function fmtClock(ms) {
      if (!ms) return ''
      const d = new Date(Number(ms))
      if (Number.isNaN(d.getTime())) return ''
      const pad = (n) => String(n).padStart(2, '0')
      return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
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

    function Message({ message, index }) {
      const [expanded, setExpanded] = useState(false)
      const isUser = message.role === 'user'
      const long = message.text.length > 1800
      const shown = long && !expanded ? message.text.slice(0, 1800) + '…' : message.text
      const rowStyle = {
        ...styles.row,
        ...(index === 0 ? styles.rowFirst : styles.rowDivider),
        ...(isUser ? styles.rowUser : styles.rowOther),
      }
      return h('div', { style: rowStyle },
        h('div', { style: styles.meta }, fmtClock(message.time)),
        h('div', { style: isUser ? { ...styles.bubble, ...styles.bubbleUser } : { ...styles.bubble, ...styles.bubbleAssistant } },
          renderMarkdown(shown),
          long
            ? h('button', { type: 'button', style: styles.more, onClick: () => setExpanded(!expanded) },
                expanded ? '收起' : `展开全文（共 ${message.text.length} 字）`)
            : null,
        ),
      )
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
      const [live, setLive] = useState(null)
      const listTimer = useRef(0)
      const bottomRef = useRef(null)

      const loadList = async () => {
        try {
          const body = await jsonFetch('/wb-sessions/list')
          setSessions(body.items || [])
          setError('')
        } catch (e) { setError(String(e.message || e)) }
      }

      const loadPage = async (id) => {
        if (!id) return
        try {
          const body = await jsonFetch(`/wb-sessions/page?id=${encodeURIComponent(id)}&max=50`)
          setMessages(body.messages || [])
          setError('')
        } catch (e) { setError(String(e.message || e)) }
      }

      useEffect(() => {
        ;(async () => {
          try {
            const health = await jsonFetch('/wb-sessions/health')
            setHasToken(Boolean(health.hasToken))
          } catch { /* 忽略 */ }
          await loadList()
        })()

        // 优先用主驾推送的事件流（SSE）触发刷新；连不上再退回定时轮询
        let source = null
        let lastKey = ''
        try {
          source = new EventSource('/wb-sessions/events')
          source.addEventListener('tick', (event) => {
            try {
              const data = JSON.parse(event.data)
              setLive(data)
              const key = `${data.sessions?.count ?? '?'}/${data.sessions?.running ?? '?'}`
              if (key !== lastKey) {
                lastKey = key
                loadList()
                if (selected) loadPage(selected)
              }
            } catch { /* 忽略坏帧 */ }
          })
          source.onerror = () => { /* 浏览器会自动重连 */ }
        } catch {
          source = null
        }

        listTimer.current = setInterval(() => {
          if (!source || source.readyState !== 1) loadList()
        }, 10000)

        return () => {
          clearInterval(listTimer.current)
          if (source) source.close()
        }
      }, [])

      useEffect(() => { if (selected) loadPage(selected) }, [selected])
      useEffect(() => {
        if (bottomRef.current && bottomRef.current.scrollIntoView) bottomRef.current.scrollIntoView({ block: 'end' })
      }, [messages.length])

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
          setTimeout(() => loadPage(selected), 700)
        } catch (e) { setError(String(e.message || e)) } finally { setBusy(false) }
      }

      const current = sessions.find((s) => s.sessionId === selected)

      return h('div', { style: styles.root },
        h('div', { style: styles.left },
          h('div', { style: styles.leftHead },
            h('span', { style: styles.title }, 'Harness 会话'),
            h('span', { style: styles.badge }, String(sessions.length)),
            h('button', { type: 'button', style: { ...styles.btn, marginLeft: 'auto', padding: '2px 8px', fontSize: 11, flex: '0 0 auto' }, onClick: loadList }, '刷新'),
          ),
          h('div', { style: styles.liveRow },
            live && live.sessions
              ? '主驾 ' + live.sessions.count + ' 会话 · ' + live.sessions.running + ' 运行'
                + (live.workbench && typeof live.workbench.latencyMs === 'number' ? ' · ' + live.workbench.latencyMs + 'ms' : '')
              : '等待主驾事件流…',
          ),
          h('div', { style: styles.list },
            sessions.length === 0
              ? h('div', { style: styles.notice }, '没有会话（主驾没开或还没会话）')
              : sessions.map((s) => h('div', {
                  key: s.sessionId,
                  style: s.sessionId === selected ? { ...styles.item, ...styles.itemActive } : styles.item,
                  onClick: () => setSelected(s.sessionId),
                },
                h('div', null,
                  (s.cwd || '').split(/[\\/]/).filter(Boolean).slice(-1)[0] || '会话',
                  s.running ? h('span', { style: { ...styles.badge, marginLeft: 6 } }, '运行中') : null),
                h('div', { style: styles.itemSub }, `${s.sessionId.slice(0, 16)}… · ${fmtTime(s.updatedAt)}`),
              )),
          ),
        ),
        h('div', { style: styles.right },
          h('div', { style: styles.rightHead },
            h('span', { style: styles.title }, current ? current.sessionId.slice(0, 26) + '…' : '选一个会话'),
            current ? h('span', { style: styles.badge }, current.cwd || '') : null,
            h('button', { type: 'button', style: { ...styles.btn, marginLeft: 'auto', padding: '2px 8px', fontSize: 11 }, onClick: () => loadPage(selected) }, '读取历史'),
          ),
          hasToken ? null : h('div', { style: styles.warn }, '主驾桥还没启用会话接口：重启一次主程序即可。'),
          error ? h('div', { style: styles.err }, error) : null,
          h('div', { style: styles.msgs },
            messages.length === 0
              ? h('div', { style: styles.notice }, selected ? '这个会话还没有可显示的消息' : '左边选一个会话看历史')
              : messages.map((m, i) => h(Message, { key: `${m.seq}`, message: m, index: i })),
            h('div', { ref: bottomRef }),
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
                h('option', { value: 'steer' }, '插入')),
              h('button', { type: 'button', style: styles.btn, disabled: !selected || busy, onClick: send }, busy ? '发送中…' : '发送'),
            ),
          ),
        ),
      )
    }

    return {
      inject: ['slots'],
      __test__: { renderMarkdown },
      apply(ctx) {
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register({ name: 'sidebar.panellist', id: 'wb-sessions', order: 45, label: () => 'Harness会话' }, Icon))
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: 'wb-sessions' }, Panel))
      },
    }
  },
})
