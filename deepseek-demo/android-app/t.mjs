const r = await fetch('http://127.0.0.1:9222/json'); console.log('status', r.status); console.log((await r.text()).slice(0,120))
