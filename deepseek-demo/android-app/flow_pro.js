(() => {
  // 1) 拦截 messages 请求，记录模型等字段
  if (!window.__of) {
    window.__of = window.fetch
    window.__reqs = []
    window.fetch = function (u, o) {
      try {
        if (o && typeof o.body === 'string' && String(u).indexOf('/messages') >= 0) {
          const j = JSON.parse(o.body)
          window.__reqs.push({
            model: j.model,
            thinking: j.thinking && j.thinking.type,
            tools: (j.tools || []).length,
            title: !!(j.title && j.title.enabled),
            safety: j.safety_check && j.safety_check.level,
          })
        }
      } catch (e) {}
      return window.__of.apply(this, arguments)
    }
  }

  // 2) 用 React 认可的写法填入文本
  const ta = document.querySelector('textarea')
  if (!ta) return 'no textarea'
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
  setter.call(ta, '用一句话说明你是谁')
  ta.dispatchEvent(new Event('input', { bubbles: true }))
  ta.focus()

  // 3) 点发送
  const btn = [...document.querySelectorAll('button')].find(
    (b) => b.getAttribute('aria-label') === '发送' && !b.disabled
  )
  if (!btn) return 'send disabled after input'
  btn.click()
  return 'sent'
})()
