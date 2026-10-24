/* A read-only tour: it highlights existing components and never activates them. */
(() => {
  const trigger = document.querySelector('[data-help-start]');
  const dialog = document.querySelector('#help-tour');
  const data = document.querySelector('#page-tour-data');
  if (!trigger || !dialog || !data) return;
  const guide = JSON.parse(data.textContent);
  const card = dialog.querySelector('.help-tour-card');
  const highlight = dialog.querySelector('.help-tour-highlight');
  const title = dialog.querySelector('#help-tour-title');
  const text = dialog.querySelector('#help-tour-text');
  const progress = dialog.querySelector('#help-tour-progress');
  const back = dialog.querySelector('#help-tour-back');
  const next = dialog.querySelector('#help-tour-next');
  let steps = [], index = 0, frame = null, previousFocus = null;

  function target(selector) {
    return [...document.querySelectorAll(selector)].find(element =>
      element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden');
  }

  function position() {
    if (!dialog.open) return;
    const element = target(steps[index].selector);
    if (!element) { close(); return; }
    const rect = element.getBoundingClientRect();
    const width = document.documentElement.clientWidth;
    const height = window.innerHeight;
    const left = Math.max(4, rect.left - 5);
    const top = Math.max(4, rect.top - 5);
    const right = Math.min(width - 4, rect.right + 5);
    const bottom = Math.min(height - 4, rect.bottom + 5);
    Object.assign(highlight.style, {left: `${left}px`, top: `${top}px`,
      width: `${Math.max(0, right - left)}px`, height: `${Math.max(0, bottom - top)}px`});
    const box = card.getBoundingClientRect();
    const x = Math.max(12, Math.min(left, width - box.width - 12));
    // Prefer an adjacent placement. Large tables use a card inside the highlighted area.
    let y = bottom + 14;
    let placement = 'below';
    if (y + box.height > height - 12) {
      y = top - box.height - 14;
      placement = 'above';
    }
    if (y < 12) {
      y = Math.max(12, height - box.height - 12);
      placement = 'inside';
    }
    card.dataset.placement = placement;
    card.style.left = `${x}px`;
    card.style.top = `${y}px`;
    card.style.setProperty('--tour-arrow-x', `${Math.max(20, Math.min(box.width - 20, (left + right) / 2 - x))}px`);
  }

  function schedulePosition() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(position);
  }

  function showStep() {
    // Re-check targets in case a responsive layout or background render changed them.
    steps = steps.filter(step => target(step.selector));
    if (!steps.length) { close(); return; }
    index = Math.min(index, steps.length - 1);
    const step = steps[index];
    title.textContent = step.title;
    text.textContent = step.text;
    progress.textContent = `${guide.title} · Step ${index + 1} of ${steps.length}`;
    back.disabled = index === 0;
    next.textContent = index === steps.length - 1 ? 'Finish' : 'Next';
    target(step.selector).scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'});
    position();
    schedulePosition();
  }

  function close() {
    dialog.close();
  }

  trigger.addEventListener('click', () => {
    previousFocus = document.activeElement;
    steps = guide.steps.filter(step => target(step.selector));
    // A heading gives even an empty register a useful starting point.
    steps.unshift({selector: '#page-content h1', title: guide.title,
      text: 'Follow the highlighted components with Next. Back revisits a step; X closes the guide.'});
    steps = steps.filter(step => target(step.selector));
    if (!steps.length) return;
    index = 0;
    dialog.showModal();
    showStep();
    next.focus({preventScroll: true});
  });
  next.addEventListener('click', () => {
    if (index === steps.length - 1) close();
    else { index++; showStep(); }
  });
  back.addEventListener('click', () => {
    if (index > 0) { index--; showStep(); }
  });
  dialog.querySelector('#help-tour-close').addEventListener('click', close);
  dialog.addEventListener('close', () => {
    cancelAnimationFrame(frame);
    if (previousFocus?.isConnected) previousFocus.focus({preventScroll: true});
  });
  window.addEventListener('resize', schedulePosition);
  window.addEventListener('scroll', schedulePosition, true);
})();
