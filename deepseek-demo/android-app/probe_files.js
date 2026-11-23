(() => {
  // 记录 input 实际收到的文件数量/名称，以及上传相关请求
  const inp = document.querySelector('input[type="file"]')
  if (!inp) return 'no file input'
  window.__picked = []
  inp.addEventListener(
    'change',
    () => {
      const fs = inp.files || []
      window.__picked = []
      for (let i = 0; i < fs.length; i++) {
        window.__picked.push(fs[i].name + ' | ' + fs[i].size + ' | ' + fs[i].type)
      }
    },
    true
  )
  // 记录 /files 上传请求与结果
  if (!window.__of2) {
    window.__of2 = window.fetch
    window.__logs = []
    window.fetch = function (u, o) {
      const url = String(u)
      const t0 = Date.now()
      const p = window.__of2.apply(this, arguments)
      if (url.indexOf('/files') >= 0) {
        p.then(function (r) {
          window.__logs.push('files ' + r.status + ' ' + (Date.now() - t0) + 'ms')
        }).catch(function (e) {
          window.__logs.push('files ERR ' + e)
        })
      }
      if (url.indexOf('/messages') >= 0) {
        window.__logs.push('messages sent')
      }
      return p
    }
  }
  window.__accept = inp.getAttribute('accept')
  return JSON.stringify({ accept: window.__accept, multiple: inp.hasAttribute('multiple') })
})()
