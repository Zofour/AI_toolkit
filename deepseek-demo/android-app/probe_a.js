(async () => {
  await new Promise((r) => setTimeout(r, 300))
  return 'async ok'
})()
