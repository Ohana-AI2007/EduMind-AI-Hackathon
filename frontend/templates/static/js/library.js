(() => {
  const ALLOWED = ['pdf', 'pptx', 'txt', 'md', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v', 'mp3', 'wav', 'm4a'];
  const VIDEO = ['mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v', 'mp3', 'wav', 'm4a'];
  const MAX = 50 * 1024 * 1024;
  const root = document.getElementById('docs');
  const videoMode = root.dataset.mode === 'video';
  const selInfo = document.getElementById('selInfo');
  const selected = new Set(selectedDocs());
  let docs = [], timer = null;

  const icon = t => ({pdf: '📕', pptx: '📊', txt: '📄', md: '📝'}[t] || '🎬');
  const saveSel = () => LS.set(ukey('docs'), [...selected]);

  function updateInfo() {
    if (videoMode) return;
    selInfo.textContent = selected.size ? `✅ ${selected.size} document(s) selected for Tutor & Quizzes.` : 'Nothing selected: the Tutor will search all your materials.';
  }

  function render() {
    root.innerHTML = '';
    const list = videoMode ? docs.filter(d => VIDEO.includes(d.file_type)) : docs;
    if (!list.length) {
      root.append(h('div', {class: 'empty card'}, h('div', {class: 'empty-emoji'}, videoMode ? '🎬' : '📚'),
        h('h3', {}, videoMode ? 'No lectures yet' : 'No materials yet'), h('p', {class: 'muted'}, 'Drop a file above to get started!')));
      return;
    }
    list.forEach(d => {
      const card = h('div', {class: 'card doc'},
        h('div', {class: 'row between'}, h('div', {class: 'doc-title'}, h('span', {class: 'doc-icon'}, icon(d.file_type)), h('b', {}, d.filename)), statusBadge(d.status)),
        h('div', {class: 'muted small'}, `${fmtSize(d.size_bytes)} · ${d.chunk_count} pieces · ${fmtDate(d.created_at)}`));
      if (d.error) card.append(h('div', {class: 'note-box err'}, '⚠️ ' + d.error));
      (d.warnings || []).forEach(w => card.append(h('div', {class: 'note-box warn'}, 'ℹ️ ' + w)));
      const actions = h('div', {class: 'row wrap'});
      if (d.status === 'ready') {
        if (videoMode) actions.append(h('button', {class: 'btn btn-primary btn-sm', type: 'button', onclick: () => window.onPickDoc && window.onPickDoc(d)}, '💬 Ask about this'));
        else actions.append(h('label', {class: 'chip-check'}, h('input', {type: 'checkbox', checked: selected.has(d.id) ? 'checked' : null, onchange: e => { e.target.checked ? selected.add(d.id) : selected.delete(d.id); saveSel(); updateInfo(); }}), ' Use this'));
      }
      if (d.status === 'awaiting_index' || d.status === 'failed')
        actions.append(h('button', {class: 'btn btn-yellow btn-sm', type: 'button', onclick: () => retry(d)}, '🔁 Retry indexing'));
      actions.append(h('button', {class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => remove(d)}, '🗑️ Delete'));
      card.append(actions);
      root.append(card);
    });
  }

  async function load() {
    clearTimeout(timer);
    try {
      docs = await api('/documents?limit=200');
      const ready = new Set(docs.filter(d => d.status === 'ready').map(d => d.id));
      [...selected].forEach(id => { if (!ready.has(id)) selected.delete(id); });
      saveSel(); updateInfo(); render();
      if (docs.some(d => d.status === 'processing')) timer = setTimeout(load, 2500);
    } catch (e) { notify(e); root.innerHTML = ''; }
  }

  async function upload(files) {
    for (const f of files) {
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      if (!ALLOWED.includes(ext)) { toast(`${f.name}: this file type isn't supported.`, 'warn'); continue; }
      if (videoMode && !VIDEO.includes(ext)) { toast(`${f.name}: please choose a video or audio file here.`, 'warn'); continue; }
      if (f.size > MAX) { toast(`${f.name} is bigger than 50 MB.`, 'warn'); continue; }
      if (f.size === 0) { toast(`${f.name} is empty.`, 'warn'); continue; }
      const fd = new FormData(); fd.append('file', f);
      try { await api('/documents/upload', {method: 'POST', form: fd}); toast(`${f.name} uploaded 🎉`, 'ok'); }
      catch (e) { notify(e); }
    }
    load();
  }

  async function retry(d) { try { await api(`/documents/${d.id}/reprocess`, {method: 'POST'}); toast('Trying again…', 'info'); load(); } catch (e) { notify(e); } }
  async function remove(d) {
    if (!confirm(`Delete "${d.filename}"? This can't be undone.`)) return;
    try { await api('/documents/' + d.id, {method: 'DELETE'}); selected.delete(d.id); saveSel(); toast('Deleted', 'ok'); load(); } catch (e) { notify(e); }
  }

  const dz = document.getElementById('dropzone'), fi = document.getElementById('fileInput');
  dz.addEventListener('click', () => fi.click());
  dz.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fi.click(); } });
  fi.addEventListener('change', () => { upload([...fi.files]); fi.value = ''; });
  ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
  dz.addEventListener('drop', e => upload([...e.dataTransfer.files]));
  load();
})();