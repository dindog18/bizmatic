// Show progress and prevent repeated clicks while the POST runs extraction.
document.querySelectorAll('.rerun-form').forEach(form => {
  const button = form.querySelector('button[type="submit"]');
  const label = button.innerHTML;
  const disabled = button.disabled;
  form.addEventListener('submit', () => {
    button.disabled = true;
    button.textContent = 'Re-running…';
    button.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', () => {
    button.innerHTML = label;
    button.disabled = disabled;
    button.removeAttribute('aria-busy');
  });
});
