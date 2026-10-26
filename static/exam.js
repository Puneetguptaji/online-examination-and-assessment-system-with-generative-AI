document.addEventListener('DOMContentLoaded', () => {
  const timer = document.getElementById('timer');
  const attempt = document.querySelector('meta[name="exam-attempt"]')?.content;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const previewToken = document.querySelector('meta[name="preview-token"]')?.content || '';
  const status = document.getElementById('save-status');
  let left = Number(timer?.dataset.remaining || 0);
  let saveQueue = Promise.resolve();
  const renderClock = () => {
    if (!timer) return;
    const mm = Math.floor(left / 60).toString().padStart(2, '0');
    const ss = (left % 60).toString().padStart(2, '0');
    timer.querySelector('strong').textContent = `${mm}:${ss}`;
    timer.classList.toggle('timer-danger', left <= 60);
  };
  renderClock();
  const ticker = window.setInterval(() => {
    left = Math.max(0, left - 1);
    renderClock();
    if (left <= 0) {
      window.clearInterval(ticker);
      const form = document.querySelector('.submit-exam-form');
      if (form) form.submit();
    }
  }, 1000);

  const save = (questionId, selected) => {
    if (status) status.textContent = 'Saving…';
    const payload = JSON.stringify({question_id: Number(questionId), selected_option: selected});
    const saveUrl = new URL(`/student/attempt/${attempt}/answer`, window.location.origin);
    if (previewToken) saveUrl.searchParams.set('preview_token', previewToken);
    saveQueue = saveQueue.then(() => fetch(saveUrl.toString(), {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: payload,
      credentials: 'same-origin'
    })).then(async (r) => {
      const data = await r.json();
      if (!r.ok || !data.ok) throw new Error(data.error || 'Save failed');
      if (status) status.textContent = 'All changes saved';
      const dot = document.querySelector(`.map-dot[data-qid="${questionId}"]`);
      if (dot) dot.classList.toggle('answered', Boolean(selected));
    }).catch(() => {
      if (status) status.textContent = 'Could not save — check connection';
    });
  };

  document.querySelectorAll('.live-option input').forEach((input) => {
    input.addEventListener('change', () => {
      const question = input.closest('.live-question');
      question.querySelectorAll('.live-option').forEach((label) => label.classList.remove('selected'));
      input.closest('.live-option').classList.add('selected');
      save(question.dataset.questionId, input.value);
    });
  });
});
