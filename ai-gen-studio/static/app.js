/* AI Gen Studio 前端 */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const S = {
  config: {}, models: null, loras: [],
  mode: 1, io: 'txt2img',
  checked: new Set(), selectedIdx: null,
  style: 'tags',
  images: [], idx: 0,
  running: false, stopFlag: false, looping: false,
  inputImage: null,
  es: null, watchResolve: null,
};

/* 是否被手机 App（WebView 壳）加载：壳会在地址后加 ?app=1 */
const IS_APP = location.search.indexOf('app=1') >= 0;

/* ---------------- 小工具 ---------------- */function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add('hidden'), 3800);
}
function fillSelect(sel, arr, val) {
  sel.innerHTML = '';
  arr.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o); });
  if (val && arr.includes(val)) sel.value = val;
}
function addLog(text, cls) {
  const box = $('#loopLog');
  const d = document.createElement('div');
  if (cls) d.className = cls;
  d.textContent = text;
  box.appendChild(d); box.scrollTop = box.scrollHeight;
}
function num(id, def) { const v = parseFloat($(id).value); return isNaN(v) ? def : v; }

/* ---------------- 初始化 ---------------- */
async function boot() {
  await loadConfig();
  await loadModels({ applyDefaults: true });
  setInterval(pollStatus, 5000); pollStatus();
  bindEvents();
  // 从别的窗口切回来时自动重扫一次（限频 8 秒），新增模型会自动出现
  let lastScan = 0;
  window.addEventListener('focus', async () => {
    const now = Date.now();
    if (now - lastScan < 8000) return;
    lastScan = now;
    const before = S.models ? S.models.text_models.map(m => m.name).join('|') : '';
    await loadModels({ keepSelection: true });
    const after = S.models ? S.models.text_models.map(m => m.name).join('|') : '';
    if (before !== after) toast('检测到模型列表变化，已刷新');
  });
}

async function loadConfig() {
  try { S.config = await (await fetch('/api/config')).json(); } catch (e) { S.config = {}; }
  if (S.config.negative && !$('#negative').value) $('#negative').value = S.config.negative;
}

async function pollStatus() {
  try {
    const d = await (await fetch('/api/status')).json();
    setDot('#dotOllama', d.ollama); setDot('#dotComfy', d.comfy); setDot('#dotWs', d.ws_connected);
    if (!d.comfy) $('#progText').textContent = 'ComfyUI 未连接';
  } catch (e) {
    setDot('#dotOllama', false); setDot('#dotComfy', false); setDot('#dotWs', false);
  }
}
function setDot(sel, on) { const e = $(sel); e.className = 'dot ' + (on ? 'on' : 'off'); }

async function loadModels(opts) {
  opts = opts || {};
  const keepSelection = !!opts.keepSelection;
  const applyDefaults = !!opts.applyDefaults;
  let prevT = '', prevI = '';
  if (keepSelection) { prevT = $('#textModel').value; prevI = $('#imageModel').value; }

  const r = await fetch('/api/models?t=' + Date.now(), { cache: 'no-store' });
  const d = await r.json();
  if (d.error) { toast(d.error, true); return null; }
  S.models = d; S.loras = d.loras || [];

  const errMsg = [d.ollama_error && 'Ollama 未连接', d.comfy_error && 'ComfyUI 未连接']
    .filter(Boolean).join('；');
  if (errMsg && errMsg !== S.lastModelErr) toast(errMsg, true);
  if (!errMsg && S.lastModelErr) toast('已连接，模型列表已刷新');
  S.lastModelErr = errMsg;

  const ts = $('#textModel'); ts.innerHTML = '';
  (d.text_models || []).forEach(m => {
    const o = document.createElement('option');
    o.value = m.name; o.dataset.vision = m.vision ? '1' : '';
    o.textContent = m.name + (m.vision ? ' 👁' : '') + (m.caps && m.caps.includes('thinking') ? ' 🧠' : '');
    ts.appendChild(o);
  });
  const wantT = prevT || localStorage.getItem('textModel');
  if (wantT && [...ts.options].some(o => o.value === wantT)) ts.value = wantT;
  if (!ts.options.length) addPlaceholder(ts, '（Ollama 未连接 — 请先启动 Ollama）');

  const im = $('#imageModel'); im.innerHTML = '';
  const g1 = document.createElement('optgroup'); g1.label = '标准模型（SD / SDXL）';
  (d.image_models.checkpoints || []).forEach(c => {
    const o = document.createElement('option'); o.value = c; o.dataset.kind = 'checkpoint'; o.textContent = c; g1.appendChild(o);
  });
  im.appendChild(g1);
  if ((d.image_models.big || []).length) {
    const g2 = document.createElement('optgroup'); g2.label = '大模型（Z-Image / Anima）';
    d.image_models.big.forEach(b => {
      const o = document.createElement('option'); o.value = b.name; o.dataset.kind = b.kind;
      o.textContent = b.name + '  [' + b.kind + ']'; g2.appendChild(o);
    });
    im.appendChild(g2);
  }
  const wantI = prevI || localStorage.getItem('imageModel');
  if (wantI && [...im.options].some(o => o.value === wantI)) im.value = wantI;
  if (!im.options.length) addPlaceholder(im, '（ComfyUI 未连接 — 请先启动 ComfyUI）');

  fillSelect($('#pSampler'), d.samplers || ['euler'], localStorage.getItem('sampler') || 'euler');
  fillSelect($('#pScheduler'), d.schedulers || ['normal'], localStorage.getItem('scheduler') || 'normal');

  if (applyDefaults) applyKindDefaults(true);
  updateVisionUI();
  return {
    text: (d.text_models || []).length,
    ckpt: (d.image_models.checkpoints || []).length,
    big: (d.image_models.big || []).length
  };
}

function modelKind() {
  const o = $('#imageModel').selectedOptions[0];
  return o ? (o.dataset.kind || 'checkpoint') : 'checkpoint';
}

/* 按模型类型套用智能默认参数 */
function applyKindDefaults(initial) {
  const kind = modelKind();
  const big = kind === 'z_image' || kind === 'anima';
  const dim = big ? 1024 : (ckptIsSDXL($('#imageModel').value) ? 1024 : 512);
  if (initial) {
    $('#pWidth').value = dim; $('#pHeight').value = dim;
  }
  if (kind === 'z_image') { $('#pSteps').value = 8; $('#pCfg').value = 1; setSel('#pSampler', 'res_multistep'); setSel('#pScheduler', 'simple'); }
  else if (kind === 'anima') { $('#pSteps').value = 30; $('#pCfg').value = 4; setSel('#pSampler', 'euler'); setSel('#pScheduler', 'simple'); }
  else if (initial) { $('#pSteps').value = 25; $('#pCfg').value = 7; }
  $('#autoSizeHint').textContent = big ? '（大模型推荐 1024）' : (dim === 1024 ? '（检测为大模型底座，推荐 1024）' : '');
}
function ckptIsSDXL(name) {
  const sizes = (S.models && S.models.ckpt_sizes) || {};
  const sz = sizes[name];
  if (sz) return sz > 6.0 * 1024 * 1024 * 1024;
  return /xl|sdxl|pony|illustrious|noob|_20|mix/i.test(name || '');
}
function setSel(sel, v) { const e = $(sel); if ([...e.options].some(o => o.value === v)) e.value = v; }

function updateVisionUI() {
  const o = $('#textModel').selectedOptions[0];
  const vision = o && o.dataset.vision === '1';
  $('#modeWrap2').classList.toggle('disabled', !vision);
  $('#mode2Radio').disabled = !vision;
  if (!vision && S.mode === 2) { S.mode = 1; $('input[name=mode][value="1"]').checked = true; }
  $('#btnStartMode2').style.display = S.mode === 2 ? '' : 'none';
  $('#btnBatch').style.display = S.mode === 2 ? 'none' : '';
  $('#pmHint').textContent = vision ? '（该模型可识图，支持模式2）' : '（该模型不识图，仅模式1）';
}

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  $('#textModel').onchange = () => { localStorage.setItem('textModel', $('#textModel').value); updateVisionUI(); };
  $('#imageModel').onchange = () => { localStorage.setItem('imageModel', $('#imageModel').value); applyKindDefaults(true); };
  $('#pSampler').onchange = () => localStorage.setItem('sampler', $('#pSampler').value);
  $('#pScheduler').onchange = () => localStorage.setItem('scheduler', $('#pScheduler').value);

  $$('input[name=mode]').forEach(r => r.onchange = () => { S.mode = +$('input[name=mode]:checked').value; updateVisionUI(); if (S.mode === 2) $('#loopBox').classList.remove('hidden'); });

  $$('#ioSeg .segbtn').forEach(b => b.onclick = () => {
    $$('#ioSeg .segbtn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    S.io = b.dataset.io;
    $('#inputPane').classList.toggle('hidden', S.io !== 'img2img');
  });

  $$('#styleSeg .segbtn').forEach(b => b.onclick = () => {
    $$('#styleSeg .segbtn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    S.style = b.dataset.style;
    localStorage.setItem('promptStyle', S.style);
  });
  const savedStyle = localStorage.getItem('promptStyle');
  if (savedStyle) {
    S.style = savedStyle;
    $$('#styleSeg .segbtn').forEach(x => x.classList.toggle('active', x.dataset.style === savedStyle));
  }

  $('#btnGenPrompts').onclick = genPrompts;
  $('#btnBatch').onclick = batchGenerate;
  $('#btnStartMode2').onclick = runMode2;
  $('#btnStop').onclick = stopAll;
  $('#btnSave').onclick = saveCurrent;
  $('#btnSavePhone').onclick = () => saveToPhone(S.images[S.idx]);
  $('#btnSavePhoneAll').onclick = saveBatchToPhone;
  $('#phoneHint').textContent = IS_APP ? '（存到 相册/电脑 文件夹）' : '（手机上可用；电脑端为普通下载）';
  $('#btnNext').onclick = () => { if (S.selectedIdx != null) startGenerate(promptTextAt(S.selectedIdx), { mode: S.mode }); else toast('先选中一条提示词', true); };
  $('#btnPrev').onclick = () => { if (S.idx > 0) { S.idx--; showImage(); } };

  // 输入图
  const drop = $('#drop');
  drop.onclick = () => $('#fileInput').click();
  $('#fileInput').onchange = e => { if (e.target.files[0]) uploadInput(e.target.files[0]); };
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) uploadInput(e.dataTransfer.files[0]); });

  // 设置
  $('#btnSettings').onclick = openSettings;
  $('#btnRefreshModels').onclick = async () => {
    const b = $('#btnRefreshModels'); b.disabled = true; b.textContent = '🔄 扫描中…';
    const c = await loadModels({ keepSelection: true });
    b.disabled = false; b.textContent = '🔄 刷新模型';
    if (c) toast(`模型已刷新：文本 ${c.text} 个 · 标准 ${c.ckpt} 个 · 大模型 ${c.big} 个`);
  };
  $('#btnCloseModal').onclick = () => $('#modal').classList.add('hidden');
  $('#btnSaveCfg').onclick = saveSettings;
}

/* ---------------- 提示词生成 ---------------- */
async function genPrompts() {
  const req = $('#requirement').value.trim();
  if (!req) return toast('请先填写需求', true);
  const model = $('#textModel').value;
  if (!model) return toast('没有可用的文本模型', true);
  const count = Math.max(1, Math.min(10, +$('#promptCount').value || 4));

  $('#promptList').innerHTML = '<div class="empty">生成中…（思考模型可能需要一些时间）</div>';
  $('#thinkText').textContent = ''; $('#thinkBox').classList.remove('hidden');
  addLog('生成 ' + count + ' 条候选提示词…', 'hd');
  let acc = '';
  await streamPost('/api/prompts', { model, requirement: req, count, image_model_hint: modelKind(), style: S.style }, ev => {
    if (ev.type === 'thinking') { $('#thinkText').textContent += ev.text; $('#thinkText').parentElement.scrollTop = 1e9; }
    else if (ev.type === 'content') { acc += ev.text; $('#promptList').innerHTML = '<div class="empty">' + esc(acc.slice(-400)) + '</div>'; }
    else if (ev.type === 'prompts') { renderPrompts(ev.prompts || []); addLog('✔ 得到 ' + (ev.prompts || []).length + ' 条候选', 'ok'); }
    else if (ev.type === 'error') { toast(ev.message, true); addLog('❌ ' + ev.message, 'no'); }
  });
}
function esc(s) { return (s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

async function streamPost(url, body, onEvent) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const line = chunk.split('\n').find(l => l.startsWith('data:'));
      if (line) { try { onEvent(JSON.parse(line.slice(5))); } catch (e) { } }
    }
  }
}

/* ---------------- 提示词卡片 ---------------- */
function renderPrompts(list) {
  S.checked = new Set(); S.selectedIdx = list.length ? 0 : null;
  const box = $('#promptList'); box.innerHTML = '';
  if (!list.length) { box.innerHTML = '<div class="empty">模型没有返回可用的提示词</div>'; return; }
  list.forEach((t, i) => {
    const card = document.createElement('div');
    card.className = 'pcard' + (i === 0 ? ' sel' : '');
    card.innerHTML = '<input type="checkbox" class="pcheck"><span class="pidx">' + (i + 1) + '</span>' +
      '<textarea class="ptext"></textarea><button class="btn sm use">用它生图</button>';
    card.querySelector('.ptext').value = t;
    card.querySelector('.pcheck').onchange = e => { if (e.target.checked) S.checked.add(i); else S.checked.delete(i); };
    card.querySelector('.ptext').onfocus = () => selectCard(i);
    card.onclick = e => { if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') selectCard(i); };
    card.querySelector('.use').onclick = e => { e.stopPropagation(); selectCard(i); startGenerate(promptTextAt(i), { mode: 1 }); };
    box.appendChild(card);
  });
}
function selectCard(i) { S.selectedIdx = i; $$('.pcard').forEach((c, j) => c.classList.toggle('sel', j === i)); }
function addPlaceholder(sel, txt) {
  const o = document.createElement('option');
  o.textContent = txt; o.value = ''; o.disabled = true; o.selected = true;
  sel.innerHTML = ''; sel.appendChild(o);
}
function promptTextAt(i) { const c = $$('.pcard')[i]; return c ? c.querySelector('.ptext').value.trim() : ''; }

/* ---------------- 生图 ---------------- */
function genBody(promptText, meta) {
  return {
    model_kind: modelKind(), model: $('#imageModel').value,
    prompt: promptText,
    negative: $('#negative') ? $('#negative').value : '',
    width: num('#pWidth', 512), height: num('#pHeight', 512),
    steps: num('#pSteps', 25), cfg: num('#pCfg', 7),
    sampler: $('#pSampler').value, scheduler: $('#pScheduler').value,
    seed: num('#pSeed', -1), batch: Math.max(1, Math.min(16, num('#pBatch', 1))),
    denoise: num('#denoise', 0.6),
    loras: (S.lorasSel || []),
    input_image: S.io === 'img2img' && S.inputImage ? S.inputImage.name : null,
    meta: Object.assign({ io_mode: S.io, requirement: $('#requirement').value.trim() }, meta || {}),
  };
}

async function startGenerate(promptText, meta) {
  if (!promptText) return { error: '提示词为空' };
  const standalone = !S.looping;
  if (standalone) { S.stopFlag = false; S.running = true; setRunning(true); }
  const r = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(genBody(promptText, meta)) });
  const d = await r.json();
  if (d.error) { toast(d.error, true); addLog('❌ ' + d.error, 'no'); if (standalone) { S.running = false; setRunning(false); } return { error: d.error }; }
  $('#imgMeta').textContent = '种子: ' + d.seed;
  const res = await watch(d.prompt_id);
  if (standalone) { S.running = false; setRunning(false); }
  return res;
}

function watch(pid) {
  return new Promise(resolve => {
    const es = new EventSource('/api/events/' + pid);
    S.es = es; S.watchResolve = resolve;
    let archived = [];
    es.onmessage = ev => {
      let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d.type === 'progress') {
        const pct = d.max ? Math.round(d.value / d.max * 100) : 0;
        $('#barFill').style.width = pct + '%';
        $('#progText').textContent = '采样 ' + d.value + '/' + d.max;
      } else if (d.type === 'image') {
        const url = '/api/image?' + new URLSearchParams(d.image).toString();
        $('#barFill').style.width = '100%'; $('#progText').textContent = '解码中…';
      } else if (d.type === 'heartbeat') {
        if (d.queue_remaining) $('#progText').textContent = '队列剩余 ' + d.queue_remaining;
      } else if (d.type === 'error') {
        toast(d.message, true); addLog('❌ ' + d.message, 'no');
      } else if (d.type === 'done') {
        archived = d.images || [];
      } else if (d.type === 'end') {
        es.close(); S.es = null; S.watchResolve = null;
        if (archived.length) { appendImages(archived); addLog('✔ 生成 ' + archived.length + ' 张（已存 temp）', 'ok'); }
        else if (!S.stopFlag) addLog('⚠ 没有产出图片', 'no');
        $('#barFill').style.width = '0%'; $('#progText').textContent = '空闲';
        resolve({ images: archived });
      }
    };
    es.onerror = () => { /* 自动重连，不处理 */ };
  });
}

function appendImages(imgs) {
  imgs.forEach(im => S.images.push(im));
  S.idx = S.images.length - imgs.length;
  renderThumbs(); showImage();
  // 手机端：出图后自动滚到结果区
  if (window.innerWidth <= 900) {
    setTimeout(() => {
      const p = $('#bigImg') && $('#bigImg').closest('.panel');
      if (p) p.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 150);
  }
}

function renderThumbs() {
  const box = $('#thumbs'); box.innerHTML = '';
  S.images.forEach((im, i) => {
    const img = document.createElement('img');
    img.src = '/api/tempfile?name=' + encodeURIComponent(im.name);
    img.className = i === S.idx ? 'on' : '';
    img.onclick = () => { S.idx = i; renderThumbs(); showImage(); };
    img.onerror = () => { img.src = '/api/image?' + new URLSearchParams(im.comfy || {}).toString(); };
    box.appendChild(img);
  });
}

function showImage() {
  const im = S.images[S.idx];
  const big = $('#bigImg');
  if (!im) { big.classList.add('hidden'); $('#stageHint').classList.remove('hidden'); $('#imgMeta').textContent = ''; return; }
  big.src = '/api/tempfile?name=' + encodeURIComponent(im.name);
  big.classList.remove('hidden'); $('#stageHint').classList.add('hidden');
  $('#saveInfo').textContent = '';
}

function setRunning(on) {
  $('#btnStop').style.display = on ? '' : 'none';
  $('#btnGenPrompts').disabled = on;
}

async function stopAll() {
  S.stopFlag = true;
  try { await fetch('/api/interrupt', { method: 'POST' }); } catch (e) { }
  if (S.es) { S.es.close(); S.es = null; }
  if (S.watchResolve) { const r = S.watchResolve; S.watchResolve = null; r({ images: [], stopped: true }); }
  S.running = false; setRunning(false);
  $('#barFill').style.width = '0%'; $('#progText').textContent = '已停止';
  addLog('■ 用户停止', 'hd');
}

/* ---------------- 批量（串行！） ---------------- */
async function batchGenerate() {
  const idxs = [...S.checked].sort((a, b) => a - b);
  if (!idxs.length) return toast('请勾选至少一条提示词', true);
  S.looping = true;
  if (!S.running) { S.stopFlag = false; S.running = true; setRunning(true); }
  addLog('开始批量：' + idxs.length + ' 条，串行执行', 'hd');
  for (const i of idxs) {
    if (S.stopFlag) break;
    const txt = promptTextAt(i);
    addLog('▶ 第 ' + (i + 1) + ' 条：' + txt.slice(0, 60) + '…', 'hd');
    await startGenerate(txt, { mode: 1 });
  }
  S.looping = false;
  S.running = false; setRunning(false);
  addLog('批量结束', 'hd');
}

/* ---------------- 模式2 ---------------- */
async function runMode2() {
  const model = $('#textModel').value;
  const o = $('#textModel').selectedOptions[0];
  if (!o || o.dataset.vision !== '1') return toast('模式2 需要选择识图模型', true);
  if (S.selectedIdx == null) return toast('请先选中一条提示词作为起点', true);
  let prompt = promptTextAt(S.selectedIdx);
  const requirement = $('#requirement').value.trim();
  if (!requirement) return toast('请填写原始需求', true);

  S.stopFlag = false; S.looping = true; S.running = true; setRunning(true);
  $('#loopBox').classList.remove('hidden');
  addLog('=== 模式2 自动循环开始（上限 16 轮，逐张评判）===', 'hd');

  for (let round = 1; round <= 16 && !S.stopFlag; round++) {
    addLog('── 第 ' + round + ' / 16 轮 ──', 'hd');
    addLog('提示词: ' + prompt);
    const res = await startGenerate(prompt, { mode: 2, round, requirement });
    if (res.error) { addLog('生图失败，终止', 'no'); break; }
    if (!res.images || !res.images.length) { addLog('无产出，终止', 'no'); break; }

    let approved = null, lastNew = '';
    for (const im of res.images) {
      if (S.stopFlag) break;
      addLog(' 评判中…');
      let j;
      try {
        const rr = await fetch('/api/judge', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model, requirement, prompt, temp_path: im.path })
        });
        j = await rr.json();
      } catch (e) { j = { error: String(e) }; }
      if (j.error) { addLog('  评判失败: ' + j.error, 'no'); continue; }
      addLog('  ' + (j.ok ? '✅ 达标' : '❌ 不达标') + ' — ' + (j.reason || ''), j.ok ? 'ok' : 'no');
      if (j.ok) { approved = im; break; }
      if (j.new_prompt) lastNew = j.new_prompt;
    }

    if (approved) {
      addLog('✅ 本轮达标，自动保存到达标目录', 'ok');
      await autoSave(approved);
      break;
    }
    if (lastNew && lastNew.trim()) {
      prompt = lastNew.trim();
      addLog('↻ 自动改写提示词，进入下一轮', 'hd');
      addPromptCard(prompt);
    } else {
      addLog('⚠ 模型未给出新提示词，沿用原提示词重试', 'no');
    }
  }
  S.looping = false;
  S.running = false; setRunning(false);
  addLog('=== 模式2 结束 ===', 'hd');
}

function addPromptCard(text) {
  const box = $('#promptList');
  const i = $$('.pcard').length;
  const card = document.createElement('div');
  card.className = 'pcard';
  card.innerHTML = '<input type="checkbox" class="pcheck"><span class="pidx">' + (i + 1) + '</span>' +
    '<textarea class="ptext"></textarea><button class="btn sm use">用它生图</button>';
  card.querySelector('.ptext').value = text;
  card.querySelector('.pcheck').onchange = e => { if (e.target.checked) S.checked.add(i); else S.checked.delete(i); };
  card.querySelector('.ptext').onfocus = () => selectCard(i);
  card.querySelector('.use').onclick = e => { e.stopPropagation(); selectCard(i); startGenerate(promptTextAt(i), { mode: 1 }); };
  card.onclick = e => { if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') selectCard(i); };
  box.appendChild(card); box.scrollTop = box.scrollHeight;
  selectCard(i);
}

async function autoSave(im) {
  const dir = S.config.save_dir;
  if (!dir) { addLog('⚠ 未设置正式保存目录，跳过自动保存（图已在 temp）', 'no'); return; }
  const r = await fetch('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ temp_path: im.path }) });
  const d = await r.json();
  if (d.error) addLog('⚠ 自动保存失败: ' + d.error, 'no'); else addLog('💾 已保存: ' + d.path, 'ok');
}

/* ---------------- 存到手机 ---------------- */
function saveToPhone(im) {
  if (!im) return toast('没有可保存的图片', true);
  if (IS_APP) {
    // 壳会拦截这个路径，把图写进手机「电脑」文件夹
    location.href = '/__aigendownload?name=' + encodeURIComponent(im.name);
  } else {
    const a = document.createElement('a');
    a.href = '/api/tempfile?name=' + encodeURIComponent(im.name);
    a.download = im.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
}

async function saveBatchToPhone() {
  if (!S.images.length) return toast('还没有可保存的图片', true);
  if (!IS_APP) return toast('「存整批」只在手机 App 里可用', true);
  addLog('开始存 ' + S.images.length + ' 张到手机「电脑」文件夹…', 'hd');
  for (const im of S.images) {
    location.href = '/__aigendownload?name=' + encodeURIComponent(im.name);
    await new Promise(r => setTimeout(r, 900));
  }
  toast('已逐张发到手机，共 ' + S.images.length + ' 张');
}

/* ---------------- 保存 ---------------- */
async function saveCurrent() {
  const im = S.images[S.idx];
  if (!im) return toast('没有可保存的图片', true);
  if (!S.config.save_dir) { toast('请先在设置里指定保存目录', true); return openSettings(); }
  const r = await fetch('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ temp_path: im.path }) });
  const d = await r.json();
  if (d.error) return toast(d.error, true);
  $('#saveInfo').textContent = '已保存: ' + d.path;
  toast('已保存到 ' + d.path);
  addLog('💾 保存: ' + d.path, 'ok');
}

/* ---------------- 输入图 ---------------- */
async function uploadInput(file) {
  const fd = new FormData(); fd.append('image', file);
  try {
    const d = await (await fetch('/api/upload', { method: 'POST', body: fd })).json();
    if (d.error) return toast(d.error, true);
    S.inputImage = d;
    const img = $('#inImg'); img.src = URL.createObjectURL(file); img.classList.remove('hidden');
    $('#dropHint').classList.add('hidden');
    $('#inInfo').textContent = '尺寸 ' + d.width + '×' + d.height + '（图生图时宽高自动采用此尺寸）';
    if (d.width && d.height) { $('#pWidth').value = d.width; $('#pHeight').value = d.height; }
  } catch (e) { toast('上传失败: ' + e, true); }
}

/* ---------------- 设置 ---------------- */
function openSettings() {
  $('#cfgComfy').value = S.config.comfy_url || '';
  $('#cfgOllama').value = S.config.ollama_url || '';
  $('#cfgTemp').value = S.config.temp_dir || '';
  $('#cfgSave').value = S.config.save_dir || '';
  $('#cfgW').value = (S.config.defaults || {}).width || 512;
  $('#cfgH').value = (S.config.defaults || {}).height || 512;
  $('#cfgSteps').value = (S.config.defaults || {}).steps || 25;
  $('#modal').classList.remove('hidden');
}
async function saveSettings() {
  const body = {
    comfy_url: $('#cfgComfy').value, ollama_url: $('#cfgOllama').value,
    temp_dir: $('#cfgTemp').value, save_dir: $('#cfgSave').value,
    defaults: { width: +$('#cfgW').value, height: +$('#cfgH').value, steps: +$('#cfgSteps').value }
  };
  const d = await (await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
  S.config = d.config || S.config;
  $('#modal').classList.add('hidden');
  toast('设置已保存');
}

boot();
