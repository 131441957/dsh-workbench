// 工作台插件模板 · 客户端（client.js）
// 关键：只要注册了 `sidebar.panellist` + `main` 两处槽位，
// 工作台顶栏会**自动**发现它（ui\workbench.js 动态扫描 `*_panelRow`），无需改工作台代码。
// 复制后要改：id / LABEL / key / PREFIX。
window.__ModuleLoader__.load({
  // ⚠️ 这个 id 必须与你 package.json 里的 name **完全一致**。
  //    不一致时浏览器会报 `could not load "<包名>"` / `duplicate factory registration`，
  //    整个客户端会白页（Failed to load plugins）。wb.py install-plugin 会提前拦住这种情况。
  id: 'wb-plugin-template',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect } = React

    const PREFIX = '/wb-template'
    const LABEL = '模板面板' // ← 顶栏上显示的名字
    const KEY = 'wb-template' // ← 与 sidebar id 一致

    function Panel() {
      const [info, setInfo] = useState(null)
      const [error, setError] = useState('')
      useEffect(() => {
        fetch(PREFIX + '/hello')
          .then((r) => r.json())
          .then(setInfo)
          .catch((e) => setError(String(e.message || e)))
      }, [])
      const styles = {
        root: { padding: 18, display: 'flex', flexDirection: 'column', gap: 10, font: 'inherit' },
        title: { fontSize: 14, fontWeight: 700 },
        row: { fontSize: 12, color: 'var(--dsw-alias-label-secondary)' },
        err: { fontSize: 12, color: 'var(--dsw-alias-label-error, #d33)' },
      }
      return h('div', { style: styles.root, 'data-wb-panel': 'template' },
        h('div', { style: styles.title }, LABEL),
        h('div', { style: styles.row }, '这个面板来自插件自己，工作台没有为它写过任何代码。'),
        info ? h('pre', { style: styles.row }, JSON.stringify(info, null, 2)) : null,
        error ? h('div', { style: styles.err }, error) : null,
      )
    }

    function Icon() {
      return h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8 },
        h('rect', { x: 4, y: 4, width: 16, height: 16, rx: 3 }),
        h('path', { d: 'M8 12h8M12 8v8' }))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register({ name: 'sidebar.panellist', id: KEY, order: 60, label: () => LABEL }, Icon))
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: KEY }, Panel))
      },
    }
  },
})
