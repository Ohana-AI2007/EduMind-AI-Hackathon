(() => {
  const $ = id => document.getElementById(id);
  const KEY = ukey('wellness');
  const data = Object.assign({moods: {}, studied: [], remind: false}, LS.get(KEY, {}));
  const save = () => LS.set(KEY, data);
  const dayStr = d => { const x = new Date(d); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };
  const today = () => dayStr(new Date());

  /* mood */
  const msgs = {'😄': 'Awesome! Ride that wave 🌊', '🙂': 'Nice and steady. 👍', '😐': 'Okay days count too. A short break might help.', '😟': "Tough day? Try a 5-minute walk, and talk to someone you trust. You've got this 💜", '😴': 'Sleepy? A glass of water and a stretch can help ✨'};
  function renderMood() {
    document.querySelectorAll('#moods button').forEach(b => b.classList.toggle('sel', data.moods[today()] === b.dataset.m));
    $('moodMsg').textContent = msgs[data.moods[today()]] || 'Tap an emoji to check in.';
    const hist = $('moodHist'); hist.innerHTML = '';
    for (let i = 6; i >= 0; i--) {
      const d = new Date(); d.setDate(d.getDate() - i);
      hist.append(h('span', {class: 'mh', title: dayStr(d)}, data.moods[dayStr(d)] || '·'));
    }
  }
  document.querySelectorAll('#moods button').forEach(b => b.addEventListener('click', () => { data.moods[today()] = b.dataset.m; save(); renderMood(); }));

  /* streak */
  function streak() {
    const set = new Set(data.studied);
    const d = new Date();
    if (!set.has(dayStr(d))) d.setDate(d.getDate() - 1);
    let n = 0;
    while (set.has(dayStr(d))) { n++; d.setDate(d.getDate() - 1); }
    return n;
  }
  function markStudied() {
    if (!data.studied.includes(today())) { data.studied.push(today()); save(); }
    $('streakNum').textContent = streak();
  }
  $('studiedBtn').addEventListener('click', () => { markStudied(); toast('Streak updated 🔥', 'ok'); celebrate(); });
  $('streakNum').textContent = streak();

  /* pomodoro */
  const TOTAL = 25 * 60;
  let left = TOTAL, iv = null;
  const fg = $('pomoRing');
  function drawPomo() {
    const m = String(Math.floor(left / 60)).padStart(2, '0'), s = String(left % 60).padStart(2, '0');
    $('pomoTime').textContent = `${m}:${s}`;
    fg.style.setProperty('--off', String(283 * (1 - left / TOTAL)));
    fg.style.animation = 'none';
  }
  $('pStart').addEventListener('click', () => {
    if (iv) { clearInterval(iv); iv = null; $('pStart').textContent = 'Resume'; return; }
    $('pStart').textContent = 'Pause';
    iv = setInterval(() => {
      left--; drawPomo();
      if (left <= 0) { clearInterval(iv); iv = null; left = TOTAL; drawPomo(); $('pStart').textContent = 'Start'; markStudied(); toast('Focus session done! Take a 5-minute break 🎉', 'ok'); celebrate(); }
    }, 1000);
  });
  $('pReset').addEventListener('click', () => { clearInterval(iv); iv = null; left = TOTAL; drawPomo(); $('pStart').textContent = 'Start'; });
  drawPomo();

  /* reminder */
  let rv = null;
  function setRemind(on) {
    clearInterval(rv); rv = null;
    if (on) rv = setInterval(() => toast('💧 Time for water and a stretch!', 'info'), 30 * 60 * 1000);
  }
  $('remind').checked = !!data.remind; setRemind(data.remind);
  $('remind').addEventListener('change', e => { data.remind = e.target.checked; save(); setRemind(data.remind); });

  /* tips */
  const tips = ['Study in short bursts: 25 minutes focus, 5 minutes rest.', 'Explain a topic out loud like you are teaching a friend.', 'Sleep helps memory. Aim for a regular bedtime.', 'Test yourself with a quiz instead of only re-reading.', 'Start with the hardest topic when your energy is highest.', 'Keep water nearby and stand up to stretch every hour.', 'Mistakes are how brains grow. Celebrate them!'];
  let ti = Math.floor(Math.random() * tips.length);
  const showTip = () => { $('tip').textContent = '💡 ' + tips[ti]; };
  $('nextTip').addEventListener('click', () => { ti = (ti + 1) % tips.length; showTip(); });
  showTip(); renderMood();
})();