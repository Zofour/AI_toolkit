(async () => {
  const H = {
    'content-type': 'application/json',
    'x-api-key': localStorage.getItem('chat-demo:api-key'),
    'anthropic-version': '2023-06-01',
  }
  const base = {
    model: 'deepseek-v4-pro',
    max_tokens: 16,
    system: 'You are helpful.',
    messages: [{ role: 'user', content: 'say ok' }],
  }
  const V = [
    ['safety_high', { safety_check: { level: 'high' } }],
    ['tools_empty', { tools: [] }],
    ['tools_readurl', { tools: [{ type: 'deepseek_read_url', name: 'deepseek_read_url' }] }],
    ['thinking_on', { thinking: { type: 'enabled' } }],
    ['title_on', { title: { enabled: true } }],
  ]
  const res = []
  for (let i = 0; i < V.length; i++) {
    const name = V[i][0]
    const extra = V[i][1]
    const body = Object.assign({}, base, extra)
    try {
      const r = await fetch('https://api.deepseek.com/anthropic/v1/messages', {
        method: 'POST',
        headers: H,
        body: JSON.stringify(body),
      })
      const t = await r.text()
      res.push(name + ' => ' + r.status + ' | ' + t.slice(0, 120))
    } catch (e) {
      res.push(name + ' => ERR ' + e)
    }
  }
  window.__probe = res
  return res.length
})()
