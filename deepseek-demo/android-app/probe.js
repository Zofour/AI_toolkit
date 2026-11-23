(async () => {
  const key = localStorage.getItem('chat-demo:api-key')
  const url = 'https://api.deepseek.com/anthropic/v1/messages'
  const base = {
    model: 'deepseek-v4-pro',
    max_tokens: 16,
    system: 'You are helpful.',
    messages: [{ role: 'user', content: 'say ok' }],
  }
  const H = { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01' }
  const V = [
    ['minimal', {}],
    ['safety', { safety_check: { level: 'high' } }],
    ['tools_empty', { tools: [] }],
    ['tools_readurl', { tools: [{ type: 'deepseek_read_url', name: 'deepseek_read_url' }] }],
    ['thinking', { thinking: { type: 'enabled' } }],
  ]
  const out = []
  for (const pair of V) {
    const n = pair[0]
    const ex = pair[1]
    try {
      const r = await fetch(url, { method: 'POST', headers: H, body: JSON.stringify(Object.assign({}, base, ex)) })
      const t = await r.text()
      out.push(n + ' => ' + r.status + ' | ' + t.slice(0, 150).replace(/\s+/g, ' '))
    } catch (e) {
      out.push(n + ' => ERR ' + e)
    }
  }
  return out.join(' @@ ')
})()
