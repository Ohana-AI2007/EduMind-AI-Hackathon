(() => {
  const $ = id => document.getElementById(id);
  const docs = selectedDocs();
  let quiz = null, idx = 0, answers = {};
  $('loadOwl').innerHTML = mascot('thinking', 120);

  function pane(name) {
    ['createPane', 'historyPane', 'playPane'].forEach(p => $(p).hidden = p !== name);
    document.querySelectorAll('#tabs .tab').forEach(t => t.classList.toggle('active', t.dataset.pane === name));
    $('tabs').hidden = name === 'playPane';
    if (name === 'historyPane') loadHistory();
  }
  document.querySelectorAll('#tabs .tab').forEach(t => t.addEventListener('click', () => pane(t.dataset.pane)));

  function updateMode() {
    const m = $('mode').value;
    $('topicsRow').hidden = m !== 'topic';
    $('docNote').textContent = m === 'document'
      ? (docs.length ? `📎 Using your ${docs.length} selected document(s).` : '⚠️ Select documents in the Library first.')
      : (docs.length ? `📎 Focusing on your ${docs.length} selected document(s).` : '');
  }
  $('mode').addEventListener('change', updateMode); updateMode();

  async function run(promise) {
    $('loading').hidden = false;
    try { return await promise(); }
    catch (e) { notify(e); return null; }
    finally { $('loading').hidden = true; }
  }

  function start(q) {
    quiz = q; idx = 0; answers = {};
    sessionStorage.setItem('edumind_quiz', JSON.stringify(q));
    $('warnBanner').innerHTML = '';
    if ((q.warnings || []).length)
      $('warnBanner').append(h('div', {class: 'banner warn'}, h('span', {}, '💡 ' + q.warnings.join(' '))));
    pane('playPane'); renderQ();
  }

  $('genForm').addEventListener('submit', async e => {
    e.preventDefault();
    const mode = $('mode').value;
    const types = [...document.querySelectorAll('input[name=qtype]:checked')].map(i => i.value);
    const topics = $('topics').value.split(',').map(s => s.trim()).filter(Boolean);
    const num = parseInt($('num').value, 10);
    if (!types.length) return toast('Pick at least one question type.', 'warn');
    if (mode === 'topic' && !topics.length) return toast('Add at least one topic.', 'warn');
    if (mode === 'document' && !docs.length) return toast('Select documents in the Library first.', 'warn');
    if (!(num >= 1 && num <= 20)) return toast('Choose 1 to 20 questions.', 'warn');
    const body = {mode, topics: mode === 'topic' ? topics : [], document_ids: docs, num_questions: num, difficulty: $('difficulty').value, question_types: types, kind: $('kind').value};
    const q = await run(() => api('/quizzes/generate', {method: 'POST', body}));
    if (q) start(q);
  });

  $('diagBtn').addEventListener('click', async () => {
    const q = await run(() => api('/quizzes/diagnostic?num_questions=8', {method: 'POST'}));
    if (q) start(q);
  });

  function renderQ() {
    const root = $('playPane'), q = quiz.questions[idx], total = quiz.questions.length;
    root.innerHTML = '';
    const src = (q.sources || [])[0];
    const card = h('div', {class: 'card q-card pop'},
      h('div', {class: 'row between wrap'},
        h('b', {}, `Question ${idx + 1} of ${total}`),
        h('div', {class: 'chips'}, h('span', {class: 'chip'}, q.topic), h('span', {class: 'chip'}, q.difficulty),
          q.verified ? h('span', {class: 'sticker sm', style: '--c:#c9f7e3;--r:-3deg'}, '✅ verified') : null)),
      (() => { const b = h('div', {class: 'bar progress-bar'}); b.innerHTML = `<i style="width:${(idx / total) * 100}%"></i>`; return b; })(),
      h('h2', {class: 'q-text'}, q.text));
    if (q.type === 'mcq') {
      const opts = h('div', {class: 'opts'});
      (q.options || []).forEach((o, i) => {
        const L = 'ABCD'[i];
        opts.append(h('button', {class: 'opt' + (answers[q.id] === L ? ' sel' : ''), type: 'button', onclick: () => { answers[q.id] = L; renderQ(); }},
          h('span', {class: 'opt-l'}, L), h('span', {}, o)));
      });
      card.append(opts);
    } else {
      const inp = h('input', {class: 'input input-lg', maxlength: '2000', placeholder: q.type === 'numerical' ? 'Type a number (e.g. 9.8)' : 'Type your answer…', value: answers[q.id] || ''});
      inp.addEventListener('input', () => { answers[q.id] = inp.value; });
      card.append(inp);
    }
    if (src) card.append(h('div', {class: 'muted small'}, '📎 Source: ' + src.label));
    const last = idx === total - 1;
    card.append(h('div', {class: 'row between wrap q-nav'},
      h('button', {class: 'btn btn-ghost', type: 'button', disabled: idx === 0 ? 'disabled' : null, onclick: () => { idx--; renderQ(); }}, '← Back'),
      h('div', {class: 'row'},
        h('button', {class: 'btn btn-ghost', type: 'button', onclick: () => { delete answers[q.id]; if (last) submit(); else { idx++; renderQ(); } }}, 'Skip ⏭️'),
        last ? h('button', {class: 'btn btn-mint btn-lg', type: 'button', onclick: submit}, 'Finish & submit 🏁')
             : h('button', {class: 'btn btn-primary', type: 'button', onclick: () => { idx++; renderQ(); }}, 'Next →'))));
    root.append(card);
  }

  async function submit() {
    const payload = quiz.questions.map(q => ({question_id: q.id, answer: (answers[q.id] || '').trim()}));
    const res = await run(() => api(`/quizzes/${quiz.id}/submit`, {method: 'POST', body: {answers: payload}}));
    if (res) { sessionStorage.setItem('edumind_result', JSON.stringify(res)); sessionStorage.removeItem('edumind_quiz'); location.href = '/quiz-results'; }
  }

  async function loadHistory() {
    const box = $('historyList');
    box.innerHTML = '';
    box.append(h('div', {class: 'card skeleton', style: 'height:80px'}));
    try {
      const rows = await api('/quizzes/history?limit=50');
      box.innerHTML = '';
      if (!rows.length) { box.append(h('div', {class: 'empty card'}, h('div', {class: 'empty-emoji'}, '🕘'), h('h3', {}, 'No quizzes yet'), h('p', {class: 'muted'}, 'Your finished quizzes will appear here.'))); return; }
      rows.forEach(r => box.append(h('a', {class: 'card hist', href: '/quiz-results?attempt=' + encodeURIComponent(r.attempt_id)},
        h('div', {}, h('b', {}, r.title), h('div', {class: 'muted small'}, `${r.kind} · ${r.difficulty} · ${fmtDate(r.submitted_at)}`)),
        h('span', {class: 'chip ' + (r.percent >= 70 ? 'strong' : r.percent >= 40 ? 'dev' : 'weak')}, Math.round(r.percent) + '%'))));
    } catch (e) { box.innerHTML = ''; notify(e); }
  }

  /* resume from dashboard "Ask anything" */
  if (new URLSearchParams(location.search).get('play') === '1') {
    try { const q = JSON.parse(sessionStorage.getItem('edumind_quiz') || 'null'); if (q && q.questions) start(q); } catch { /* ignore */ }
  }
})();