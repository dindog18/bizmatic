/* Row editors keep the backend's validated JSON contract; secrets are never prefilled. */
(() => {
  'use strict';
  const form = document.querySelector('[data-connection-form]');
  if (!form) return;
  const editors = [];
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  const configurations = [
    ['arguments', false, false, 'Add argument', 'Argument'],
    ['environment', true, true, 'Add environment variable', 'Environment variable'],
    ['environment_passthrough', false, false, 'Add variable', 'Environment variable name'],
    ['http_headers', true, true, 'Add header', 'Header'],
    ['env_http_headers', true, false, 'Add variable', 'Header from environment variable'],
  ];
  for (const [name, pairs, secret, addLabel, label] of configurations) {
    const input = form.elements[name];
    const section = input.closest('[data-field]');
    const heading = section.querySelector('label');
    heading.removeAttribute('for');
    heading.id = `${name}-heading`;
    input.hidden = true;
    const list = make('div', 'encoder-field-rows');
    list.setAttribute('role', 'group');
    list.setAttribute('aria-labelledby', heading.id);
    const add = make('button', 'btn btn-falcon-default encoder-add-row', `+ ${addLabel}`);
    add.type = 'button';
    let nextId = 0;
    const append = (key = '', value = '', focus = false) => {
      const row = make('div', 'encoder-field-row');
      const id = ++nextId;
      for (const [index, content] of (pairs ? [key, value] : [key]).entries()) {
        const cell = make('input', 'form-control');
        cell.type = secret && index === 1 ? 'password' : 'text';
        cell.autocomplete = secret ? 'new-password' : 'off';
        cell.placeholder = pairs ? (index === 0 ? 'Key' : name === 'env_http_headers' ? 'Environment variable name' : 'Value') : label;
        cell.value = content;
        cell.setAttribute('aria-label', `${label} ${id}${pairs ? index === 0 ? ' key' : ' value' : ''}`);
        cell.addEventListener('input', () => cell.setCustomValidity(''));
        row.append(cell);
      }
      const remove = make('button', 'btn btn-falcon-default encoder-remove-row', '×');
      remove.type = 'button';
      remove.setAttribute('aria-label', `Remove ${label.toLowerCase()} ${id}`);
      remove.addEventListener('click', () => {
        row.remove();
        if (!list.children.length) append();
        add.focus();
      });
      row.append(remove);
      list.append(row);
      if (focus) row.querySelector('input').focus();
    };
    let initial;
    try { initial = JSON.parse(input.value || (pairs ? '{}' : '[]')); } catch { initial = pairs ? {} : []; }
    const rows = pairs ? Object.entries(initial) : initial.map(value => [value, '']);
    if (rows.length) rows.forEach(([key, value]) => append(key, value)); else append();
    add.addEventListener('click', () => append('', '', true));
    input.after(list, add);
    editors.push(() => {
      if (input.disabled) return;
      const result = pairs ? Object.create(null) : [];
      for (const row of list.children) {
        const cells = row.querySelectorAll('input');
        const key = pairs ? cells[0].value.trim() : cells[0].value;
        const value = pairs ? cells[1].value : '';
        if (!key && !value) continue;
        if (pairs && (!key || Object.hasOwn(result, key))) {
          cells[0].setCustomValidity(key ? 'Each key must be unique.' : 'Enter a key for this value.');
          cells[0].reportValidity();
          return false;
        }
        if (pairs) result[key] = value; else result.push(key);
      }
      input.value = secret && !Object.keys(result).length ? '' : JSON.stringify(result);
      return true;
    });
  }
  const transport = form.elements.transport;
  transport.hidden = true;
  transport.closest('[data-field]').querySelector('label').textContent = 'Type';
  const choices = make('div', 'encoder-transport');
  choices.setAttribute('role', 'group');
  choices.setAttribute('aria-label', 'MCP type');
  for (const option of transport.options) {
    const button = make('button', 'btn', option.textContent);
    button.type = 'button';
    button.dataset.value = option.value;
    button.addEventListener('click', () => { transport.value = option.value; transport.dispatchEvent(new Event('change', {bubbles:true})); });
    choices.append(button);
  }
  const sync = () => { for (const button of choices.children) button.setAttribute('aria-pressed', String(button.dataset.value === transport.value)); };
  transport.addEventListener('change', sync);
  sync();
  transport.after(choices);
  form.addEventListener('submit', event => {
    if (editors.some(serialize => serialize() === false)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  });
})();
