'use strict';
const $ = id => document.getElementById(id);
let references = [], config = null, busy = false, dragDepth = 0;
let currentScale = '2k';
let resolutions = {
  "512": {"1:1": [512, 512], "4:3": [608, 448], "3:4": [448, 608], "3:2": [624, 416], "2:3": [416, 624], "16:9": [688, 384], "9:16": [384, 688]},
  "1k": {"1:1": [1024, 1024], "4:3": [1200, 896], "3:4": [896, 1200], "3:2": [1264, 848], "2:3": [848, 1264], "16:9": [1376, 768], "9:16": [768, 1376]},
  "2k": {"1:1": [2048, 2048], "4:3": [2400, 1792], "3:4": [1792, 2400], "3:2": [2528, 1696], "2:3": [1696, 2528], "16:9": [2752, 1536], "9:16": [1536, 2752]}
};
const historyUrls = [];
function showError(message = '') { $('error').textContent = message; $('error').hidden = !message; }
function status(label, mode = 'online') { $('connection-label').textContent = label; $('connection').className = mode; }
function updateRatios() {
  const selected = $('ratio').value || '1:1';
  const table = resolutions[currentScale] || resolutions['2k'];
  $('ratio').replaceChildren(...Object.entries(table).map(([ratio, size]) => new Option(`${ratio} · ${size[0]} × ${size[1]}`, ratio)));
  if (table[selected]) $('ratio').value = selected;
}
function updateControls() {
  $('generate').disabled = busy || !config;
  $('generate-label').textContent = busy ? 'Generating…' : references.length ? 'Edit image' : 'Generate';
  $('mode-label').textContent = references.length ? 'Image editing' : 'Text to image';
  $('image-count').textContent = `${references.length} / 10`;
  for (const id of ['attach','new-chat','new-mobile','prompt','ratio','steps','transparent','cpu-offload','seed-random','memory-mode','attention-mode','kv-cache','vae-tiling','performance-reset']) if ($(id)) $(id).disabled = busy;
  if ($('seed')) $('seed').disabled = busy || ($('seed-random') && $('seed-random').checked);
  if ($('header-cpu-offload')) $('header-cpu-offload').disabled = busy;
  document.querySelectorAll('.suggestions button').forEach(button => button.disabled = busy);
  document.querySelectorAll('.scale-btn').forEach(btn => btn.disabled = busy);
}
function renderPreviews() {
  $('previews').replaceChildren();
  references.forEach((ref, index) => {
    const box = document.createElement('div'); box.className = 'preview';
    const image = document.createElement('img'); image.src = ref.url; image.alt = ref.file.name;
    const label = document.createElement('small'); label.textContent = `${index + 1}`;
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
    remove.setAttribute('aria-label', `Remove image ${index + 1}: ${ref.file.name}`); remove.disabled = busy;
    remove.onclick = () => { URL.revokeObjectURL(ref.url); references.splice(index, 1); renderPreviews(); };
    box.append(image, label, remove); $('previews').append(box);
  });
  updateControls();
}
async function addFiles(files) {
  if (busy) return;
  showError();
  const errors = [];
  for (const file of files) {
    if (references.length >= 10) { errors.push('You can attach up to 10 images.'); break; }
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { errors.push(`${file.name}: use PNG, JPG or WebP.`); continue; }
    if (file.size > 15 * 1024 * 1024) { errors.push(`${file.name}: maximum 15 MB per image.`); continue; }
    if (references.reduce((sum, ref) => sum + ref.file.size, 0) + file.size > 45 * 1024 * 1024) { errors.push('Maximum total upload is 45 MB.'); continue; }
    references.push({file, url: URL.createObjectURL(file)});
  }
  renderPreviews(); showError(errors.join(' '));
}
function clearReferences() { references.forEach(ref => URL.revokeObjectURL(ref.url)); references = []; renderPreviews(); }
$('attach').onclick = () => $('file-input').click();
$('reference-suggestion').onclick = () => $('file-input').click();
$('file-input').onchange = event => { addFiles([...event.target.files]); event.target.value = ''; };
document.addEventListener('dragenter', event => { if ([...event.dataTransfer.types].includes('Files')) { event.preventDefault(); dragDepth++; if (!busy) $('drop-overlay').hidden = false; } });
document.addEventListener('dragover', event => { if ([...event.dataTransfer.types].includes('Files')) event.preventDefault(); });
document.addEventListener('dragleave', event => { if (dragDepth) dragDepth--; if (!dragDepth) $('drop-overlay').hidden = true; });
document.addEventListener('drop', event => { event.preventDefault(); dragDepth = 0; $('drop-overlay').hidden = true; addFiles([...event.dataTransfer.files]); });
window.addEventListener('blur', () => { dragDepth = 0; $('drop-overlay').hidden = true; });
document.querySelectorAll('[data-prompt]').forEach(button => button.onclick = () => { $('prompt').value = button.dataset.prompt; $('transparent').checked = button.dataset.transparent === 'true'; updateNote(); $('prompt').focus(); });
function updateNote() { $('composer-note').textContent = $('transparent').checked ? 'Adds Qwen’s recommended transparency wording to your prompt. Output depends on the model.' : 'Drop images anywhere · PNG, JPG, WebP · Ctrl / ⌘ + Enter to generate'; }
$('transparent').onchange = updateNote;
$('prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); if (!busy) $('composer').requestSubmit(); } });
$('new-chat').onclick = () => {
  if (busy) return;
  $('messages').replaceChildren(); $('welcome').hidden = false; $('prompt').value = ''; clearReferences(); showError();
  if ($('seed')) $('seed').value = '42';
  if ($('seed-random')) { $('seed-random').checked = false; $('seed').disabled = false; }
  historyUrls.splice(0).forEach(url => URL.revokeObjectURL(url));
};
$('new-mobile').onclick = () => $('new-chat').click();
function readBase64(file) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = () => reject(new Error('Could not read an attached image.')); reader.readAsDataURL(file); }); }
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The server could not complete the request.');
  return data;
}
function makeMessage(prompt, refs, request) {
  const article = document.createElement('article'); article.className = 'message';
  
  const headerRow = document.createElement('div'); headerRow.className = 'message-header-row';
  const heading = document.createElement('div'); heading.className = 'message-heading'; heading.textContent = 'You';

  const actions = document.createElement('div'); actions.className = 'message-header-actions';

  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.className = 'msg-btn';
  copyBtn.title = 'Copy prompt to clipboard';
  copyBtn.innerHTML = '<span>📋</span> <span>Copy prompt</span>';
  copyBtn.onclick = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      const span = copyBtn.querySelectorAll('span')[1];
      const prev = span.textContent;
      span.textContent = 'Copied!';
      copyBtn.classList.add('success');
      setTimeout(() => { span.textContent = prev; copyBtn.classList.remove('success'); }, 1800);
    } catch (e) {
      showError('Could not copy to clipboard.');
    }
  };

  const savedRefs = [...refs];
  const reuseBtn = document.createElement('button');
  reuseBtn.type = 'button';
  reuseBtn.className = 'msg-btn';
  reuseBtn.title = 'Reuse this prompt and reference images';
  reuseBtn.innerHTML = '<span>↺</span> <span>Reuse</span>';
  reuseBtn.onclick = () => {
    if (busy) return;
    $('prompt').value = prompt;
    clearReferences();
    if (savedRefs.length > 0) {
      savedRefs.forEach(r => {
        references.push({ file: r.file, url: URL.createObjectURL(r.file) });
      });
      renderPreviews();
    }
    if (request) {
      if (request.scale && request.scale !== currentScale) {
        currentScale = request.scale;
        document.querySelectorAll('.scale-btn').forEach(b => b.classList.toggle('active', b.dataset.scale === currentScale));
        updateRatios();
      }
      if (request.ratio && $('ratio')) $('ratio').value = request.ratio;
      if (request.steps && $('steps')) $('steps').value = request.steps;
      if (typeof request.transparent === 'boolean' && $('transparent')) {
        $('transparent').checked = request.transparent;
        updateNote();
      }
    }
    if (request) {
      $('seed').value = request.seed ?? 42;
      $('seed-random').checked = false;
      $('memory-mode').value = request.cpu_offload === false ? 'gpu' : 'offload';
      $('attention-mode').value = request.attention_mode || 'standard';
      $('kv-cache').checked = request.use_kv_cache !== false;
      $('vae-tiling').checked = request.vae_tiling === true;
      updatePerformance(); updateControls();
    }
    $('prompt').focus();
    const span = reuseBtn.querySelectorAll('span')[1];
    const prev = span.textContent;
    span.textContent = 'Loaded!';
    reuseBtn.classList.add('success');
    setTimeout(() => { span.textContent = prev; reuseBtn.classList.remove('success'); }, 1200);
  };

  actions.append(copyBtn, reuseBtn);
  headerRow.append(heading, actions);
  article.append(headerRow);

  const text = document.createElement('p'); text.textContent = prompt;
  article.append(text);
  if (refs.length) {
    const list = document.createElement('div'); list.className = 'message-refs';
    refs.forEach(ref => {
      const img = document.createElement('img');
      const url = URL.createObjectURL(ref.file);
      historyUrls.push(url);
      img.src = url;
      img.alt = ref.file.name;
      list.append(img);
    });
    article.append(list);
  }

  // Calculate target aspect ratio & dimensions
  const scale = (request && request.scale) || currentScale;
  const ratio = (request && request.ratio) || '1:1';
  const table = resolutions[scale] || resolutions['2k'];
  const [width, height] = table[ratio] || [2048, 2048];
  const aspectVal = width / height;

  const wrapper = document.createElement('div');
  wrapper.className = 'gen-placeholder-wrapper';

  const placeholder = document.createElement('div');
  placeholder.className = 'generating-placeholder';
  placeholder.style.aspectRatio = `${width} / ${height}`;
  placeholder.style.width = `min(100%, calc(650px * ${aspectVal}))`;

  placeholder.innerHTML = `
    <div class="gen-hud">
      <div class="gen-bar-wrap">
        <div class="gen-bar-fill" style="width: 0%;"></div>
      </div>
      <div class="gen-info">
        <div class="gen-status-text">Starting generation…</div>
        <div class="gen-step-badge">Step 0 / ${(request && request.steps) || 40}</div>
        <div class="gen-meta-tag">${ratio} · ${width} × ${height}</div>
      </div>
    </div>
  `;

  wrapper.append(placeholder);
  article.append(wrapper);
  $('messages').append(article);
  $('welcome').hidden = true;
  article.scrollIntoView({behavior:'smooth', block:'start'});

  const barFill = placeholder.querySelector('.gen-bar-fill');
  const statusText = placeholder.querySelector('.gen-status-text');
  const stepBadge = placeholder.querySelector('.gen-step-badge');

  function updateProgress(pct, step, totalSteps, status) {
    const clampedPct = Math.max(0, Math.min(100, Math.round(pct)));
    if (barFill) barFill.style.width = `${clampedPct}%`;
    if (stepBadge && totalSteps) {
      stepBadge.textContent = `Step ${step || 0} / ${totalSteps}`;
    }
    if (statusText && status) {
      statusText.textContent = status;
    }
  }

  return { article, placeholder, wrapper, updateProgress };
}

async function pollJob(id, message, totalSteps) {
  let failures = 0;
  let lastRealProgress = 0;

  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 450));
    let job;
    try {
      job = await api(`/api/jobs/${id}`);
      failures = 0;
    } catch (error) {
      failures++;
      if (message.updateProgress) message.updateProgress(lastRealProgress, 0, totalSteps, 'Reconnecting to server…');
      if (failures >= 15) throw new Error(`Could not reconnect. The job may still be running. ID: ${id}`);
      continue;
    }

    if (job.status === 'failed') throw new Error(job.error);
    if (job.status === 'complete') {
      return job;
    }

    const backendPct = typeof job.progress === 'number' ? job.progress : 0;
    const currentStep = job.step || 0;
    const jobTotalSteps = job.total_steps || totalSteps;
    const elapsedText = (typeof job.elapsed === 'number' && job.elapsed > 0) ? ` · ${job.elapsed}s` : '';

    let statusText = 'Generating image…';
    if (job.stage === 'preparing' || backendPct === 0) {
      statusText = `Preparing model & latents…${elapsedText}`;
    } else if (backendPct > 0) {
      statusText = `Denoising step ${currentStep} of ${jobTotalSteps}…${elapsedText}`;
    }

    lastRealProgress = backendPct;
    if (message.updateProgress) {
      message.updateProgress(backendPct, currentStep, jobTotalSteps, statusText);
    }
  }
}
document.querySelectorAll('.scale-btn').forEach(btn => {
  btn.onclick = () => {
    if (busy) return;
    document.querySelectorAll('.scale-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentScale = btn.dataset.scale;
    updateRatios();
  };
});

function updateCpuOffloadUI(source) {
  const isOffload = source ? source.checked : ($('header-cpu-offload') ? $('header-cpu-offload').checked : ($('cpu-offload') ? $('cpu-offload').checked : true));
  if ($('cpu-offload')) $('cpu-offload').checked = isOffload;
  if ($('header-cpu-offload')) $('header-cpu-offload').checked = isOffload;

  const sidebar = $('sidebar-memory');
  const sidebarTitle = $('sidebar-memory-title');
  const sidebarSub = $('sidebar-memory-sub');
  const sidebarDot = $('sidebar-badge-dot');

  if (isOffload) {
    if (sidebar) sidebar.classList.remove('off');
    if (sidebarTitle) sidebarTitle.textContent = 'Memory Optimized';
    if (sidebarSub) sidebarSub.textContent = 'Selected: CPU offload · BF16';
    if (sidebarDot) sidebarDot.classList.remove('off');
  } else {
    if (sidebar) sidebar.classList.add('off');
    if (sidebarTitle) sidebarTitle.textContent = 'Full GPU Mode';
    if (sidebarSub) sidebarSub.textContent = 'Selected: full GPU · >30 GB weights';
    if (sidebarDot) sidebarDot.classList.add('off');
  }
}
if ($('cpu-offload')) $('cpu-offload').onchange = e => updateCpuOffloadUI(e.target);
if ($('header-cpu-offload')) $('header-cpu-offload').onchange = e => updateCpuOffloadUI(e.target);

function updatePerformance() {
  $('header-cpu-offload').checked = $('memory-mode').value === 'offload';
  updateCpuOffloadUI();
  const modes = {standard: 'Standard', compiled: 'Compiled standard', flex: 'Compiled Flex'};
  $('performance-summary').textContent = `${$('memory-mode').value === 'offload' ? 'CPU offload' : 'Full GPU'} · ${modes[$('attention-mode').value]}`;
  document.querySelector('.memory-tag').lastChild.textContent = $('memory-mode').value === 'offload' ? ' CPU OFFLOAD' : ' FULL GPU';
}
for (const id of ['memory-mode', 'attention-mode', 'kv-cache', 'vae-tiling']) $(id).onchange = updatePerformance;
$('performance-reset').onclick = () => {
  $('memory-mode').value = 'offload'; $('attention-mode').value = 'standard';
  $('kv-cache').checked = true; $('vae-tiling').checked = false; updatePerformance();
};

if ($('seed-random')) {
  $('seed-random').onchange = () => {
    if ($('seed-random').checked) {
      if ($('seed')) {
        $('seed').dataset.prev = $('seed').value;
        $('seed').disabled = true;
      }
    } else {
      if ($('seed')) {
        $('seed').disabled = busy;
        if (!$('seed').value) $('seed').value = $('seed').dataset.prev || '42';
      }
    }
  };
}

$('composer').onsubmit = async event => {
  event.preventDefault(); if (busy || !config) return;
  showError();
  const prompt = $('prompt').value.trim();
  if (!prompt) return showError('Describe the image or edits you want.');
  for (const id of ['steps']) if (!$(id).reportValidity()) return;
  const isRandom = ($('seed-random') && $('seed-random').checked) || $('seed').value === '';
  if (!isRandom && $('seed') && !$('seed').reportValidity()) return;
  const request = {
    prompt,
    scale: currentScale,
    ratio: $('ratio').value,
    steps: Number($('steps').value),
    seed: isRandom ? null : Number($('seed').value),
    transparent: $('transparent').checked,
    cpu_offload: $('memory-mode').value === 'offload',
    attention_mode: $('attention-mode').value,
    use_kv_cache: $('kv-cache').checked,
    vae_tiling: $('vae-tiling').checked
  };
  busy = true; renderPreviews(); status('Working locally', 'working');
  let message;
  try {
    request.images = await Promise.all(references.map(ref => readBase64(ref.file)));
    message = makeMessage(prompt, references, request);
    const initial = await api('/api/jobs', {method:'POST', headers:{'Content-Type':'application/json','X-Qwen-Token':config.token}, body:JSON.stringify(request)});
    request.seed = initial.seed;
    const job = await pollJob(initial.id, message, request.steps);

    const heading = document.createElement('div'); heading.className = 'message-heading'; heading.textContent = 'Qwen Image 2.1';
    const timeStr = job.generation_time_formatted || (typeof job.generation_time === 'number' ? (job.generation_time < 60 ? `${job.generation_time}s` : `${Math.floor(job.generation_time / 60)}m ${(job.generation_time % 60).toFixed(1)}s`) : (typeof job.duration === 'number' ? `${job.duration}s` : ''));
    const timePart = timeStr ? ` · ${timeStr}` : '';
    const image = document.createElement('img'); image.className = 'result'; image.src = job.url; image.alt = `Generated result: ${prompt}`;
    image.title = 'Click to open in default system photo viewer' + (timeStr ? ` · Generated in ${timeStr}` : '');
    image.style.cursor = 'pointer';
    image.style.animation = 'appear 0.4s ease';
    image.onclick = () => {
      fetch(`/api/open/${job.id}.png`).catch(console.error);
    };

    const metadata = document.createElement('div'); metadata.className = 'metadata'; metadata.textContent = `${job.width} × ${job.height} · ${request.steps} steps${timePart} · Seed ${job.seed}${request.transparent ? ' · Transparency requested' : ''}`;
    if (timeStr) metadata.title = `Generation time: ${timeStr}`;
    const actions = document.createElement('div'); actions.className = 'result-actions';
    const download = document.createElement('a'); download.href = job.url; download.download = `qwen-${job.seed}.png`; download.textContent = 'Download PNG';
    const openSystem = document.createElement('button'); openSystem.type = 'button'; openSystem.textContent = 'Open in System Viewer';
    openSystem.onclick = () => {
      fetch(`/api/open/${job.id}.png`).catch(console.error);
    };
    const reuse = document.createElement('button'); reuse.type = 'button'; reuse.textContent = 'Use as reference';
    reuse.onclick = async () => { if (busy) return; try { const response = await fetch(job.url); if (!response.ok) throw new Error('Could not load the saved image.'); const blob = await response.blob(); await addFiles([new File([blob], `qwen-${job.seed}.png`, {type:'image/png'})]); $('prompt').focus(); } catch (error) { showError(error.message); } };
    actions.append(download, openSystem, reuse);

    const metrics = document.createElement('div'); metrics.className = 'run-metrics';
    const m = job.metrics || {};
    const mode = {standard: 'Standard', compiled: 'Compiled standard', flex: 'Compiled Flex'}[request.attention_mode];
    metrics.textContent = `${request.cpu_offload ? 'CPU offload' : 'Full GPU'} · ${mode} · KV cache ${request.use_kv_cache ? 'ON' : 'OFF'} · VAE tiling ${request.vae_tiling ? 'ON' : 'OFF'}`;
    if (typeof m.setup_s === 'number') metrics.textContent += `\nSetup ${m.setup_s}s${m.reloaded ? ' (model reloaded)' : ' (reused)'} · Prepare + first step ${m.first_step_s ?? '—'}s · Remaining steps ${m.remaining_steps_s ?? '—'}s · Finish ${m.finish_s ?? '—'}s`;
    if (typeof m.peak_vram_gib === 'number') metrics.textContent += `\nPeak PyTorch GPU memory: ${m.peak_vram_gib} GiB (excludes other apps)`;
    message.wrapper.replaceWith(heading, image, metadata, metrics, actions);
    $('prompt').value = ''; clearReferences(); status('Model ready');
  } catch (error) {
    if (message && message.placeholder) {
      message.placeholder.innerHTML = `
        <div class="gen-hud" style="padding:24px;">
          <div class="gen-ring-wrap" style="width:50px;height:50px;">
            <span style="font-size:26px;color:#ff8585;">✕</span>
          </div>
          <div class="gen-status-text" style="color:#ffb3b3;">Generation failed</div>
          <div class="generation-error" style="max-width:480px;font-size:11px;margin:8px 0;">${error.message}</div>
        </div>
      `;
    }
    showError(error.message); status('Ready to retry');
  } finally { busy = false; renderPreviews(); }
};
let heartbeatTimer = null;
function initHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  const sendHeartbeat = async () => {
    if (!config) return;
    try {
      await fetch('/api/heartbeat', {
        method: 'POST',
        headers: { 'X-Qwen-Token': config.token }
      });
    } catch (e) {}
  };
  heartbeatTimer = setInterval(sendHeartbeat, 3000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) sendHeartbeat();
  });
  window.addEventListener('focus', sendHeartbeat);
}

let statsTimer = null;
async function fetchHardwareStats() {
  if (!config) return;
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();

    // GPU stats
    if (data.gpu) {
      if ($('gpu-load')) $('gpu-load').textContent = `${data.gpu.load}%`;
      if ($('gpu-temp')) {
        const temp = data.gpu.temp;
        $('gpu-temp').textContent = `${temp}°C`;
        $('gpu-temp').className = `hw-temp ${temp >= 80 ? 'hot' : temp >= 65 ? 'warm' : 'cool'}`;
      }
      if ($('gpu-vram')) $('gpu-vram').textContent = `${data.gpu.mem_used} / ${data.gpu.mem_total} GB`;
      if ($('hw-gpu')) $('hw-gpu').style.display = 'inline-flex';
    } else if ($('hw-gpu')) {
      $('hw-gpu').style.display = 'none';
    }

    // CPU stats
    if (data.cpu && $('cpu-load')) {
      $('cpu-load').textContent = `${data.cpu.load}%`;
    }

    // RAM stats
    if (data.ram) {
      if ($('ram-load')) $('ram-load').textContent = `${data.ram.load}%`;
      if ($('ram-val')) $('ram-val').textContent = `${data.ram.used_gb} / ${data.ram.total_gb} GB`;
    }
  } catch (e) {}
}

function initStatsMonitor() {
  if (statsTimer) clearInterval(statsTimer);
  fetchHardwareStats();
  statsTimer = setInterval(fetchHardwareStats, 2000);
}

window.addEventListener('beforeunload', () => {
  if (config) {
    const url = '/api/shutdown?token=' + encodeURIComponent(config.token);
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon(url);
      } else {
        fetch(url, {
          method: 'POST',
          headers: { 'X-Qwen-Token': config.token },
          keepalive: true
        });
      }
    } catch (e) {
      try {
        fetch(url, {
          method: 'POST',
          headers: { 'X-Qwen-Token': config.token },
          keepalive: true
        });
      } catch (e2) {}
    }
  }
});

async function connect() {
  try {
    config = await api('/api/config');
    if (config.resolutions) resolutions = config.resolutions;
    updateRatios();
    if (config.venv_root && $('env-path')) {
      const parts = config.venv_root.replace(/\\/g, '/').split('/').filter(Boolean);
      const shortName = parts.slice(-2).join('/');
      $('env-path').textContent = shortName || config.venv_root;
      $('env-path').title = `Environment: ${config.venv_root}`;
    }
    status(config.busy ? 'Model busy in another request' : config.loaded ? 'Model ready' : 'Local · ready'); updateControls();
    const support = config.acceleration || {available: false, reason: 'Restart the updated server to check compiler support.'};
    for (const option of $('attention-mode').options) if (option.value !== 'standard') option.disabled = !support.available;
    $('acceleration-note').textContent = support.available ? 'Compiler package detected; compatibility is verified on first generation. First compilation may take several minutes.' : support.reason;
    updatePerformance();
    initHeartbeat();
    initStatsMonitor();
  } catch (error) {
    config = null;
    status('Server offline', 'offline');
    updateControls();
    if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
    setTimeout(connect, 4000);
  }
}
connect();
