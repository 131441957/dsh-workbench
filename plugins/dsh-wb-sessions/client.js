/* ══════════════════════════════════════════════════════════════════════════
 * dsh-wb-sessions —— 客户端半（页面里的「Harness会话」面板）
 * --------------------------------------------------------------------------
 * 注册方式：`__ModuleLoader__.load({ id, factory })`，**id 必须等于 package.json 的 name**。
 *
 * ── 它渲染什么 ───────────────────────────────────────────────────────────
 *   左栏 290px：标题行（单行省略 + 计数 + 刷新）／liveRow（主驾 N 会话 · M 运行 · Xms）
 *              ／过滤框 + 排序（recent | workspace | running）
 *   分组：workspace 模式下按会话 cwd 聚合，组头可折叠（组名 + 计数胶囊 + sticky）
 *   行：运行中圆点 / 标题（单行省略）／短 id + 相对时间；点开读历史，底部可投递消息
 *   历史渲染：**自己渲染 Markdown**（标题/粗体/行内代码/代码块/列表/表格/引用/分隔线/链接），
 *            用户消息靠右主题色、助手靠左描边、每条只留精确到秒的时间、长内容折叠（>1800 字）
 *
 * ── 数据来自 ─────────────────────────────────────────────────────────────
 *   /wb-sessions/{list,page,send,workspaces,events}；events 是 SSE（3 秒一帧 tick）
 *   数量/运行态变化才刷新，SSE 没连上就退回 10 秒轮询
 *
 * ── 改这个文件要守住 ─────────────────────────────────────────────────────
 * ① 面板根节点带 `data-wb-panel`（遮罩依赖它）
 * ② 分组键必须是 cwd，组名用工作区显示名（default-workspace → 「默认工作区」），
 *    别拿会话标题当组头（会把组头显示成标题）
 * ③ 时间只显示到秒，**不要**加「助手/用户」文字标签（用户明确要求）
 *
 * ── 改完怎么验证 ─────────────────────────────────────────────────────────
 *   node --check <本文件>；node tools\test-markdown.mjs（渲染器离线单测）
 *   node tools\test-sessions-group.mjs（分组回归）
 * ══════════════════════════════════════════════════════════════════════════ */
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
      controls: { display: 'flex', gap: 6, padding: '6px 8px', borderBottom: '1px solid var(--dsw-alias-border-secondary)' },
      search: { flex: '1 1 auto', minWidth: 0, padding: '3px 6px', fontSize: 11, borderRadius: 6, border: '1px solid var(--dsw-alias-border-secondary)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', font: 'inherit' },
      sortSelect: { flex: '0 0 auto', padding: '2px 4px', fontSize: 11, borderRadius: 6, border: '1px solid var(--dsw-alias-border-secondary)', background: 'var(--dsw-alias-bg-secondary)', color: 'var(--dsw-alias-label-primary)', font: 'inherit' },
      groupBlock: { marginTop: 6, paddingBottom: 2 },
      group: { display: 'flex', alignItems: 'center', gap: 6, padding: '9px 10px 7px', position: 'sticky', top: 0, zIndex: 1, background: 'var(--dsw-alias-bg-base)', borderTop: '1px solid var(--dsw-alias-border-secondary)', cursor: 'pointer' },
      groupChevron: { fontSize: 9, opacity: 0.6, flex: '0 0 auto', width: 10 },
      groupName: { fontSize: 11.5, fontWeight: 700, color: 'var(--dsw-alias-label-primary)', letterSpacing: '.2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: '1 1 auto', minWidth: 0 },
      groupCount: { fontSize: 10, padding: '0 6px', borderRadius: 8, background: 'var(--dsw-alias-bg-secondary)', color: 'var(--dsw-alias-label-secondary)', flex: '0 0 auto' },
      itemTop: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 },
      dot: { width: 6, height: 6, borderRadius: 3, background: 'var(--dsw-alias-border-secondary)', flex: '0 0 auto' },
      itemTitle: { fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: '1 1 auto', minWidth: 0 },
      itemTime: { fontSize: 10, color: 'var(--dsw-alias-label-secondary)', flex: '0 0 auto' },      liveRow: { padding: '5px 10px 6px', fontSize: 10, color: 'var(--dsw-alias-label-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', borderBottom: '1px solid var(--dsw-alias-border-secondary)' },
      title: { fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0, flex: '0 1 auto' },
      badge: { fontSize: 10, padding: '1px 6px', borderRadius: 8, background: 'var(--dsw-alias-bg-secondary)', color: 'var(--dsw-alias-label-secondary)', flex: '0 0 auto' },
      list: { flex: 1, overflow: 'auto', minHeight: 0 },
      item: { padding: '6px 10px 7px 20px', borderBottom: '1px solid var(--dsw-alias-border-secondary)', borderLeft: '2px solid transparent', cursor: 'pointer', fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
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

    // 标题来源：桥补的 s.title，或摘要里的 projections.values.title
    function sessionTitle(s) {
      const direct = String(s.title || '').trim()
      if (direct) return direct
      const projected = s.projections && s.projections.values ? s.projections.values.title : ''
      return typeof projected === 'string' ? projected.trim() : ''
    }

    // 会话显示名：优先标题，其次 cwd 末段，最后 id 短号
    function sessionLabel(s) {
      const title = sessionTitle(s)
      if (title) return title
      const tail = String(s.cwd || '').split(/[\\/]/).filter(Boolean).slice(-1)[0]
      if (tail) return tail
      return '#' + s.sessionId.replace('session-', '').slice(0, 8)
    }

    // 分组：按**工作区（cwd）**分组，组头用工作区显示名，不是会话标题。
    // 曾经这里用了 sessionLabel（优先标题），结果每条会话自成一组建头全是标题——已修。
    function wsKey(path) {
      return String(path || '').replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()
    }
    function wsTail(path) {
      return String(path || '').split(/[\\/]/).filter(Boolean).slice(-1)[0] || ''
    }
    // 行标题：有标题就显示标题；没有标题时，工作区模式下用短号避免与组头重复
    function rowTitle(s, group) {
      const title = sessionTitle(s)
      if (title) return title
      const short = '#' + s.sessionId.replace('session-', '').slice(0, 8)
      if (group && group.key && String(group.key).startsWith('ws:')) return short
      return sessionLabel(s)
    }
    function buildGroups(items, mode, needle, wsByPath) {
      const q = needle ? needle.toLowerCase() : ''
      const list = items.filter((s) => !q
        || (s.cwd || '').toLowerCase().includes(q)
        || s.sessionId.toLowerCase().includes(q)
        || String(sessionTitle(s)).toLowerCase().includes(q))
      const sorted = list.slice().sort((a, b) => {
        if (mode === 'running' && Boolean(a.running) !== Boolean(b.running)) return a.running ? -1 : 1
        return (b.updatedAt || 0) - (a.updatedAt || 0)
      })
      if (mode === 'workspace') {
        const map = new Map()
        for (const s of sorted) {
          const key = wsKey(s.cwd)
          const meta = key && wsByPath ? wsByPath.get(key) : null
          const label = (meta && meta.label) || wsTail(s.cwd) || '未归属工作区'
          if (!map.has(key)) map.set(key, { label, items: [] })
          map.get(key).items.push(s)
        }
        return Array.from(map.entries())
          .map(([key, g]) => ({ key: 'ws:' + key, label: g.label, items: g.items }))
          .sort((a, b) => {
            const at = Math.max(...a.items.map((s) => s.updatedAt || 0))
            const bt = Math.max(...b.items.map((s) => s.updatedAt || 0))
            return bt - at || a.label.localeCompare(b.label)
          })
      }
      return [{ key: 'all', label: '全部会话', items: sorted }]
    }
    function fmtTime(ms) {      if (!ms) return ''
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
      const [query, setQuery] = useState('')
      const [sortMode, setSortMode] = useState('workspace')
      const [wsIndex, setWsIndex] = useState(new Map())
      const [collapsedGroups, setCollapsedGroups] = useState(new Set())
      const listTimer = useRef(0)
      const bottomRef = useRef(null)

      const loadList = async () => {
        try {
          const [body, wss] = await Promise.all([
            jsonFetch('/wb-sessions/list'),
            jsonFetch('/wb-sessions/workspaces').catch(() => null),
          ])
          setSessions(body.items || [])
          if (wss && Array.isArray(wss.workspaces)) {
            const next = new Map()
            for (const w of wss.workspaces) {
              const key = w.key || wsKey(w.path)
              if (key) next.set(key, w)
            }
            setWsIndex(next)
          }
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

      const toggleGroup = (key) => {
        setCollapsedGroups((prev) => {
          const next = new Set(prev)
          if (next.has(key)) next.delete(key)
          else next.add(key)
          return next
        })
      }
      const groups = useMemo(() => buildGroups(sessions, sortMode, query, wsIndex), [sessions, sortMode, query, wsIndex])

      const current = sessions.find((s) => s.sessionId === selected)

      return h('div', { style: styles.root, 'data-wb-panel': 'sessions' },
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
          h('div', { style: styles.controls },
            h('input', {
              style: styles.search,
              placeholder: '过滤会话…',
              value: query,
              onChange: (e) => setQuery(e.target.value),
            }),
            h('select', {
              value: sortMode,
              onChange: (e) => setSortMode(e.target.value),
              style: styles.sortSelect,
            },
              h('option', { value: 'recent' }, '最近活动'),
              h('option', { value: 'workspace' }, '按工作区'),
              h('option', { value: 'running' }, '运行优先'),
            ),
          ),
          h('div', { style: styles.list },
            groups.length === 0
              ? h('div', { style: styles.notice }, sessions.length === 0 ? '没有会话（主驾没开或还没会话）' : '没有匹配的会话')
              : groups.map((g) => {
                  const collapsed = collapsedGroups.has(g.key)
                  return h('div', { key: g.key, style: styles.groupBlock },
                    h('div', {
                      style: styles.group,
                      onClick: () => toggleGroup(g.key),
                      title: collapsed ? '展开' : '收起',
                    },
                      h('span', { style: styles.groupChevron }, collapsed ? '▸' : '▾'),
                      h('span', { style: styles.groupName }, g.label),
                      h('span', { style: styles.groupCount }, String(g.items.length)),
                    ),
                    collapsed ? null : g.items.map((s) => h('div', {
                      key: s.sessionId,
                      style: s.sessionId === selected ? { ...styles.item, ...styles.itemActive } : styles.item,
                      onClick: () => setSelected(s.sessionId),
                      title: s.sessionId + '\n' + (s.cwd || ''),
                    },
                      h('div', { style: styles.itemTop },
                        h('span', { style: s.running ? { ...styles.dot, background: '#4caf50', boxShadow: '0 0 0 3px rgba(76,175,80,.18)' } : styles.dot }),
                        h('span', { style: styles.itemTitle }, rowTitle(s, g)),
                        h('span', { style: styles.itemTime }, fmtTime(s.updatedAt)),
                      ),
                      h('div', { style: styles.itemSub }, s.sessionId.replace('session-', '').slice(0, 8) + (s.blank ? ' · 空会话' : '')),
                    )),
                  )
                }),
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
      __test__: { renderMarkdown, buildGroups, wsKey, sessionLabel },
      apply(ctx) {
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register({ name: 'sidebar.panellist', id: 'wb-sessions', order: 45, label: () => 'Harness会话' }, Icon))
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: 'wb-sessions' }, Panel))
      },
    }
  },
})
