(async () => {
  const root = document.getElementById('prog');
  let p;
  try { p = await api('/progress'); } catch (e) { root.innerHTML = ''; notify(e); return; }
  root.innerHTML = '';
  if (p.overall_mastery == null && !p.quizzes_taken) {
    const d = h('div', {class: 'empty card'});
    d.innerHTML = mascot('encouraging', 120);
    d.append(h('h3', {}, 'Your progress story starts here!'), h('p', {class: 'muted'}, 'Take a quiz and Edu will track your mastery.'), h('a', {class: 'btn btn-primary', href: '/quizzes'}, 'Take a quiz 🎯'));
    root.append(d);
    return;
  }
  const colors = {weak: '#ff6b8b', developing: '#ffc933', strong: '#2fd392'};
  const cv = id => { const c = h('canvas', {id}); return c; };

  const top = h('div', {class: 'grid grid-3 stagger'});
  const rc = h('div', {class: 'card center'}, h('h3', {}, '🧠 Mastery'));
  const rr = h('div', {}); rr.innerHTML = ring((p.overall_mastery || 0) * 100, {size: 130, label: 'overall'});
  rc.append(rr);
  top.append(rc,
    h('div', {class: 'card center'}, h('h3', {}, '🎯 Quizzes'), h('div', {class: 'big-num'}, p.quizzes_taken), h('small', {class: 'muted'}, 'avg ' + (p.average_score != null ? Math.round(p.average_score) + '%' : '—'))),
    h('div', {class: 'card center'}, h('h3', {}, '✅ Accuracy'), h('div', {class: 'big-num'}, p.accuracy != null ? Math.round(p.accuracy * 100) + '%' : '—'), h('small', {class: 'muted'}, `${p.topics_tracked} topics tracked`)));
  root.append(top);

  const charts = h('div', {class: 'grid grid-2'},
    h('div', {class: 'card'}, h('h3', {}, '📈 Mastery over time'), h('div', {class: 'chart-box'}, cv('cTimeline'))),
    h('div', {class: 'card'}, h('h3', {}, '🏆 Quiz scores'), h('div', {class: 'chart-box'}, cv('cScores'))));
  root.append(charts, h('div', {class: 'card'}, h('h3', {}, '📚 Topic mastery'), h('div', {class: 'chart-box tall'}, cv('cTopics'))));

  const opts = (max) => ({responsive: true, maintainAspectRatio: false, plugins: {legend: {display: false}}, scales: {y: {min: 0, max, ticks: {callback: v => v + '%'}}}});
  if (window.Chart) {
    const tl = p.mastery_timeline || [];
    new Chart(document.getElementById('cTimeline'), {type: 'line', data: {labels: tl.map(t => t.date), datasets: [{data: tl.map(t => Math.round(t.overall_mastery * 100)), borderColor: '#7c5cff', backgroundColor: 'rgba(124,92,255,.15)', fill: true, tension: .35, pointRadius: 4}]}, options: opts(100)});
    const qs = [...(p.quiz_scores || [])].reverse();
    new Chart(document.getElementById('cScores'), {type: 'bar', data: {labels: qs.map((q, i) => '#' + (i + 1)), datasets: [{data: qs.map(q => Math.round(q.percent)), backgroundColor: qs.map(q => q.percent >= 70 ? '#2fd392' : q.percent >= 40 ? '#ffc933' : '#ff6b8b'), borderRadius: 10}]}, options: opts(100)});
    const tp = p.topics || [];
    new Chart(document.getElementById('cTopics'), {type: 'bar', data: {labels: tp.map(t => t.topic.length > 28 ? t.topic.slice(0, 27) + '…' : t.topic), datasets: [{data: tp.map(t => Math.round(t.mastery * 100)), backgroundColor: tp.map(t => colors[t.status]), borderRadius: 10}]}, options: {...opts(100), indexAxis: 'y', scales: {x: {min: 0, max: 100, ticks: {callback: v => v + '%'}}}}});
  } else root.append(h('div', {class: 'banner warn'}, 'Charts could not load (offline?).'));

  const rec = p.recommendations || {};
  const lower = h('div', {class: 'grid grid-2'});
  const rev = h('div', {class: 'card'}, h('h3', {}, '🔁 Revision priorities'));
  (rec.revision_priorities || []).length
    ? rec.revision_priorities.forEach(r => rev.append(h('div', {class: 'rev-item'}, h('div', {class: 'row between'}, h('b', {}, r.topic), h('span', {class: 'chip ' + (r.mastery < 0.4 ? 'weak' : r.mastery < 0.7 ? 'dev' : 'strong')}, pct(r.mastery) + '%')), h('div', {class: 'muted small'}, r.reason))))
    : rev.append(h('p', {class: 'muted'}, 'Nothing to revise yet.'));
  const prac = h('div', {class: 'card'}, h('h3', {}, '📝 Practice these again'));
  (rec.practice_questions || []).length
    ? rec.practice_questions.forEach(q => prac.append(h('div', {class: 'rev-item'}, h('span', {class: 'chip'}, q.topic), h('div', {}, q.text))))
    : prac.append(h('p', {class: 'muted'}, 'No practice questions queued.'));
  prac.append(h('a', {class: 'btn btn-primary btn-sm', href: '/quizzes'}, 'Make a quiz 🎲'));
  lower.append(rev, prac);
  root.append(lower);

  root.append(h('div', {class: 'card'}, h('h3', {}, '🕘 Recent activity'),
    (p.recent_activity || []).length
      ? h('ul', {class: 'feed'}, p.recent_activity.map(a => h('li', {}, activityText(a), h('small', {class: 'muted'}, ' · ' + fmtDate(a.created_at)))))
      : h('p', {class: 'muted'}, 'No activity yet.')));
})();