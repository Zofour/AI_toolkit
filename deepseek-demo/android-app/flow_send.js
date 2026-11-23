(() => {
  const ta = document.querySelector('textarea')
  if (!ta) return 'no textarea'
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
  setter.call(ta, '这两张图分别是什么内容？各一句话')
  ta.dispatchEvent(new Event('input', { bubbles: true }))
  const btn = [...document.querySelectorAll('button')].find(
    (b) => b.getAttribute('aria-label') === '发送' && !b.disabled
  )
  if (!btn) return 'send disabled'
  btn.click()
  return 'sent'
})()
