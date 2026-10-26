document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach((node) => {
    window.setTimeout(() => {
      if (node.isConnected) {
        node.style.transition = 'opacity .35s';
        node.style.opacity = '0';
        window.setTimeout(() => node.remove(), 380);
      }
    }, 6500);
  });

  const buildWorkingStatus = (status, task) => {
    status.hidden = false;
    status.className = 'ai-request-status is-running';
    status.replaceChildren();

    const row = document.createElement('div');
    row.className = 'ai-status-row';
    const spinner = document.createElement('span');
    spinner.className = 'ai-spinner';
    spinner.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('div');
    copy.className = 'ai-status-copy';
    const title = document.createElement('strong');
    title.textContent = task === 'feedback' ? 'Preparing your learning review' : 'Drafting questions with Gemini';
    const detail = document.createElement('span');
    detail.textContent = 'Waiting for a real Gemini response; no sample output is being shown.';
    copy.append(title, detail);
    row.append(spinner, copy);

    const progress = document.createElement('div');
    progress.className = 'ai-indeterminate-track';
    progress.setAttribute('aria-hidden', 'true');
    const moving = document.createElement('span');
    progress.append(moving);

    const elapsed = document.createElement('div');
    elapsed.className = 'ai-elapsed';
    elapsed.textContent = 'Elapsed: 0 seconds';
    status.append(row, progress, elapsed);
    return elapsed;
  };

  document.querySelectorAll('form[data-ai-form]').forEach((form) => {
    const button = form.querySelector('[data-ai-submit]');
    const status = form.querySelector('[data-ai-status]');
    if (!button || !status) return;

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (form.dataset.aiBusy === 'true') return;
      form.dataset.aiBusy = 'true';
      const task = form.dataset.aiForm;
      const originalButton = button.innerHTML;
      const elapsed = buildWorkingStatus(status, task);
      const started = Date.now();
      const timer = window.setInterval(() => {
        const seconds = Math.floor((Date.now() - started) / 1000);
        elapsed.textContent = `Elapsed: ${seconds} second${seconds === 1 ? '' : 's'}`;
      }, 1000);
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.innerHTML = '<span class="ai-spinner ai-spinner-small" aria-hidden="true"></span> Gemini is working…';

      try {
        const response = await fetch(form.action || window.location.href, {
          method: 'POST',
          body: new FormData(form),
          headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'same-origin'
        });
        let result;
        try {
          result = await response.json();
        } catch (_) {
          throw new Error(`The server returned an unexpected response (HTTP ${response.status}).`);
        }
        if (!response.ok || !result.ok) {
          throw new Error(result.error || `Gemini request failed (HTTP ${response.status}).`);
        }

        status.className = 'ai-request-status is-success';
        status.replaceChildren();
        const success = document.createElement('strong');
        const usedModel = result.model ? ` (${result.model})` : '';
        success.textContent = task === 'feedback'
          ? (result.cached ? `Your saved AI review${usedModel} is ready.` : `Gemini${usedModel} created a review from the student’s submitted answers.`)
          : `Gemini${usedModel} returned ${result.count} question draft${result.count === 1 ? '' : 's'}.`;
        const next = document.createElement('span');
        next.textContent = task === 'feedback'
          ? 'Opening the student result…'
          : 'Opening the teacher review queue. Drafts are not published automatically.';
        const link = document.createElement('a');
        const destination = new URL(result.redirect, window.location.href);
        if (destination.origin !== window.location.origin) throw new Error('The server returned an invalid destination.');
        link.href = destination.href;
        link.textContent = task === 'feedback' ? 'Open learning review' : 'Open AI review queue';
        status.append(success, next, link);
        window.setTimeout(() => window.location.assign(destination.href), 900);
      } catch (error) {
        status.className = 'ai-request-status is-error';
        status.replaceChildren();
        const title = document.createElement('strong');
        title.textContent = 'Gemini could not complete the request.';
        const detail = document.createElement('span');
        detail.textContent = error.message || 'Check the server connection and try again.';
        status.append(title, detail);
      } finally {
        window.clearInterval(timer);
        button.disabled = false;
        button.removeAttribute('aria-busy');
        button.innerHTML = originalButton;
        form.dataset.aiBusy = 'false';
      }
    });
  });
});
