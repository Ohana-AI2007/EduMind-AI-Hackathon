(() => {
  const $ = id => document.getElementById(id);
  const chat = $('chat'), sid = sessionId();
  let busy = false;

  const docs = selectedDocs();
  $('docInfo').textContent = docs.length ? `📎 Using ${docs.length} selected document(s).` : '📚 Searching all your materials. (Pick documents in the Library to focus.)';

  const scroll = () => chat.lastElementChild && chat.lastElementChild.scrollIntoView({behavior: 'smooth', block: 'end'});
  const bubble = (role, ...kids) => h('div', {class: 'bubble ' + role}, ...kids);

  function intro() {
    const d = h('div', {class: 'chat-empty'});
    d.innerHTML = mascot('happy', 110);
    d.append(h('h3', {}, 'Ask me anything about your notes!'), h('p', {class: 'muted'}, "I answer only from what you uploaded, and I'll tell you when something isn't there."));
    chat.append(d);
  }

  async function loadHistory() {
    try {
      const rows = await api(`/tutor/history?session_id=${encodeURIComponent(sid)}&limit=50`);
      rows.forEach(m => chat.append(m.role === 'user' ? bubble('user', m.content) : bubble('bot', h('div', {class: 'answer'}, m.content.replace(/\[S\d+\]/g, '')))));
    } catch (e) { notify(e); }
    if (!chat.children.length) intro();
    scroll();
  }

  async function send(question) {
    if (busy || !question.trim()) return;
    busy = true; $('sendBtn').disabled = true;
    const empty = chat.querySelector('.chat-empty'); if (empty) empty.remove();
    chat.append(bubble('user', question));
    const typing = bubble('bot', h('span', {class: 'dots'}, h('i'), h('i'), h('i')));
    chat.append(typing); scroll();
    try {
      const body = {question, session_id: sid, mode: $('mode').value, language: $('lang').value, allow_outside_knowledge: $('outside').checked};
      if (docs.length) body.document_ids = docs;
      const data = await api('/tutor/chat', {method: 'POST', body});
      typing.replaceWith(bubble('bot', assistantCard(data, s => send(s))));
    } catch (e) {
      typing.replaceWith(bubble('bot', h('div', {class: 'answer'}, '😕 I could not answer that: ' + (e.message || 'please try again.'))));
      notify(e);
    }
    busy = false; $('sendBtn').disabled = false; scroll();
  }

  $('chatForm').addEventListener('submit', e => { e.preventDefault(); const q = $('q').value.trim(); $('q').value = ''; send(q); });
  $('q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('chatForm').requestSubmit(); } });
  $('newChat').addEventListener('click', () => { newSession(); location.reload(); });
  loadHistory();
})();