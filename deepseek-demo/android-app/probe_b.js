(async () => {
  try {
    const r = await fetch('https://api.deepseek.com/anthropic/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': localStorage.getItem('chat-demo:api-key'),
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'deepseek-v4-pro',
        max_tokens: 16,
        system: 'You are helpful.',
        messages: [{ role: 'user', content: 'say ok' }],
      }),
    })
    const t = await r.text()
    return 'status=' + r.status + ' body=' + t.slice(0, 200)
  } catch (e) {
    return 'ERR ' + e
  }
})()
