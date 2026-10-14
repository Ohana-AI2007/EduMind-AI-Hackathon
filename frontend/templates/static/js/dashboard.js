(async () => {
  const dash = document.getElementById('dash');
  const user = getUser();
  document.getElementById('heroOwl').innerHTML = mascot('happy', 130);
  const hour = new Date().getHours();
  document.getElementById('greeting').textContent = `${hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'}, ${user}! 👋`;

  /* ask anything */
  const out = document.getElementById('askOut');
  document.getElementById('askForm').addEventListener('submit', async e => {
    e.preventDefault();
    const input = document.getElementById('askInput'), msg = input.value.trim();
    if (!msg) return;
    out.innerHTML = '';
    out.append(h('div', {class: 'typing-row'}, h('span', {class: 'dots'}, h('i'), h('i'), h('i')), ' Edu is thinking…'));
    try {
      const r = await api('/orchestrate', {method: 'POST', body: {message: msg, session_id: sessionId(), document_ids: selectedDocs().length ? selectedDocs() : undefined, mode: 'simple', language: 'en', allow_outside_knowledge: false}});
      out.innerHTML = '';
      if (r.status === 'needs_documents') {
        out.append(h('p', {}, r.message), h('a', {class: 'btn btn-yellow', href: '/library'}, 'Upload materials 📤'));
      } else if (r.tutor) {
        out.append(assistantCard(r.tutor, null));
      } else if (r.quiz) {
        sessionStorage.setItem('edumind_quiz', JSON.stringify(r.quiz));
        out.append(h('p', {}, r.message), h('a', {class: 'btn btn-primary', href: '/quizzes?play=1'}, 'Start the quiz 🎯'));
      } else if (r.progress) {
        out.append(h('p', {}, r.message), h('a', {class: 'btn btn-mint', href: '/progress'}, 'Open my progress 📈'));
      } else if (r.recommendations) {
        out.append(h('p', {}, r.message), h('ul', {}, (r.recommendations.suggestions || []).map(s => h('li', {}, s))));
      } else out.append(h('p', {}, r.message));
    } catch (err) { out.innerHTML = ''; notify(err); }
  });

  /* stats */
  let p;
  try { p = await api('/progress'); } catch (e) { dash.innerHTML = ''; notify(e); return; }
  dash.innerHTML = '';
  const rec = p.recommendations || {};
  const hasMastery = p.overall_mastery != null;
  if (!hasMastery) document.getElementById('heroSub').textContent = 'New here? Upload notes, then take a quick diagnostic quiz!';

  const masteryCard = h('div', {class: 'card center'}, h('h3', {}, '🧠 Overall mastery'));
  if (hasMastery) {
    const r = h('div', {}); r.innerHTML = ring(p.overall_mastery * 100, {size: 150, label: 'mastered'});
    masteryCard.append(r, h('span', {class: 'sticker', style: '--c:#fff3b0;--r:-3deg'}, p.overall_mastery >= 0.7 ? '🏆 Mastered!' : '🚀 Keep going!'));
  } else {
    masteryCard.append(h('div', {class: 'empty-emoji'}, '🌱'), h('p', {class: 'muted'}, 'Take your first quiz to start growing your mastery!'), h('a', {class: 'btn btn-pink', href: '/quizzes'}, 'First quiz 🎯'));
  }
  const statsCard = h('div', {class: 'card'}, h('h3', {}, '📊 My stats'),
    h('div', {class: 'stat-grid'},
      h('div', {class: 'stat'}, h('b', {}, p.quizzes_taken), h('small', {}, 'quizzes')),
      h('div', {class: 'stat'}, h('b', {}, p.average_score != null ? Math.round(p.average_score) + '%' : '—'), h('small', {}, 'avg score')),
      h('div', {class: 'stat'}, h('b', {}, p.topics_tracked), h('small', {}, 'topics'))),
    h('h4', {}, '💪 Strong'), h('div', {class: 'chips'}, (p.strong_topics || []).length ? p.strong_topics.slice(0, 6).map(t => h('span', {class: 'chip strong'}, t)) : h('span', {class: 'muted small'}, 'Coming soon!')),
    h('h4', {}, '🌱 Needs love'), h('div', {class: 'chips'}, (p.weak_topics || []).length ? p.weak_topics.slice(0, 6).map(t => h('span', {class: 'chip weak'}, t)) : h('span', {class: 'muted small'}, 'None yet')));
  const actCard = h('div', {class: 'card'}, h('h3', {}, '🕘 Recent activity'),
    (p.recent_activity || []).length
      ? h('ul', {class: 'feed'}, p.recent_activity.slice(0, 6).map(a => h('li', {}, activityText(a), h('small', {class: 'muted'}, ' · ' + fmtDate(a.created_at)))))
      : h('p', {class: 'muted'}, 'Nothing yet. Your adventures will show up here!'));
  dash.append(masteryCard, statsCard, actCard);

  const recCard = h('section', {class: 'card'}, h('h3', {}, '🧭 Recommended next'));
  const items = h('div', {class: 'grid grid-3'});
  (rec.revision_priorities || []).slice(0, 3).forEach(r => items.append(h('div', {class: 'rec-card'}, h('b', {}, r.topic), h('p', {class: 'muted small'}, r.reason), h('a', {class: 'btn btn-sm btn-primary', href: '/quizzes'}, 'Practice'))));
  (rec.next_topics || []).filter(t => !(rec.revision_priorities || []).some(r => r.topic === t)).slice(0, 3)
    .forEach(t => items.append(h('div', {class: 'rec-card new'}, h('b', {}, t), h('p', {class: 'muted small'}, 'New topic to explore'), h('a', {class: 'btn btn-sm btn-mint', href: '/tutor'}, 'Learn'))));
  if (!items.children.length) (rec.suggestions || ['Upload some notes to get started!']).forEach(s => items.append(h('div', {class: 'rec-card'}, s)));
  recCard.append(items);
  dash.parentNode.insertBefore(recCard, dash.nextSibling);
})();