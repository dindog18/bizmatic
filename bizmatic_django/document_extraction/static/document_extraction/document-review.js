/* Preview saved originals and edit Markdown before submitting it to Django. */
(() => {
  'use strict';
  const vendorUrl = new URL('vendors/', document.currentScript.src);
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const xml = text => {
    const doc = new DOMParser().parseFromString(text, 'application/xml');
    if (doc.querySelector('parsererror')) throw new Error('The document content could not be read.');
    return doc;
  };
  const nodes = (parent, name) => [...parent.getElementsByTagNameNS('*', name)];
  const attribute = (node, name) => [...node.attributes].find(attr => attr.localName === name)?.value;
  const zipText = async (zip, path) => {
    const entry = zip.file(path);
    if (!entry) throw new Error('The file is missing its document content.');
    return entry.async('string');
  };
  const table = rows => {
    const wrapper = element('div', undefined, 'table-responsive');
    const grid = element('table', undefined, 'table table-sm preview-table mb-0');
    const body = element('tbody');
    for (const row of rows.slice(0, 500)) {
      const tr = element('tr');
      for (const value of row) tr.append(element('td', value));
      body.append(tr);
    }
    grid.append(body);
    wrapper.append(grid);
    if (rows.length > 500) wrapper.append(element('p', 'Showing the first 500 rows. Download the original for all rows.', 'fs-11 mt-2'));
    return wrapper;
  };
  // CSV respects quoted cells, including embedded commas, quotes and newlines.
  const csvRows = text => {
    const rows = []; let row = [], cell = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      if (char === '"') {
        if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
        else quoted = !quoted;
      } else if (!quoted && (char === ',' || char === '\n' || char === '\r')) {
        row.push(cell); cell = '';
        if (char !== ',') {
          rows.push(row); row = [];
          if (char === '\r' && text[i + 1] === '\n') i++;
        }
      } else cell += char;
    }
    if (cell || row.length) rows.push([...row, cell]);
    return rows;
  };
  const wordPreview = async file => {
    const zip = await JSZip.loadAsync(file);
    const doc = xml(await zipText(zip, 'word/document.xml'));
    const paper = element('article', undefined, 'office-paper');
    const text = node => nodes(node, 't').map(part => part.textContent).join('');
    for (const child of nodes(doc, 'body')[0].children) {
      if (child.localName === 'p') {
        const style = nodes(child, 'pStyle')[0];
        const heading = style && /heading([1-6])/i.exec(attribute(style, 'val') || '');
        paper.append(element(heading ? `h${heading[1]}` : 'p', text(child)));
      } else if (child.localName === 'tbl') {
        paper.append(table(nodes(child, 'tr').map(row => [...row.children]
          .filter(cell => cell.localName === 'tc').map(text))));
      }
    }
    return paper;
  };
  const excelPreview = async file => {
    const zip = await JSZip.loadAsync(file);
    const book = xml(await zipText(zip, 'xl/workbook.xml'));
    const relations = xml(await zipText(zip, 'xl/_rels/workbook.xml.rels'));
    const shared = zip.file('xl/sharedStrings.xml')
      ? nodes(xml(await zipText(zip, 'xl/sharedStrings.xml')), 'si').map(item => nodes(item, 't').map(part => part.textContent).join('')) : [];
    const wrapper = element('div', undefined, 'office-paper');
    const select = element('select', undefined, 'form-select form-select-sm mb-3');
    select.setAttribute('aria-label', 'Worksheet');
    const content = element('div');
    const sheets = nodes(book, 'sheet');
    sheets.forEach((sheet, index) => {
      const option = element('option', attribute(sheet, 'name'));
      option.value = String(index); select.append(option);
    });
    let version = 0;
    const render = async () => {
      const current = ++version;
      const relation = nodes(relations, 'Relationship').find(item => attribute(item, 'Id') === attribute(sheets[select.value], 'id'));
      const target = relation && attribute(relation, 'Target');
      if (!target || attribute(relation, 'TargetMode') === 'External') throw new Error('This worksheet cannot be previewed.');
      const path = target.startsWith('/') ? target.slice(1) : `xl/${target}`;
      const sheet = xml(await zipText(zip, path));
      const rows = nodes(sheet, 'row').map(row => {
        const values = [];
        for (const cell of nodes(row, 'c')) {
          const letters = (attribute(cell, 'r') || '').replace(/\d/g, '');
          const column = [...letters].reduce((sum, letter) => sum * 26 + letter.charCodeAt(0) - 64, 0) - 1;
          // Keep sparse columns, with Excel's maximum column count as a bound.
          if (column < 0 || column >= 16384) continue;
          const value = nodes(cell, 'v')[0]?.textContent || '';
          values[column] = attribute(cell, 't') === 's' ? shared[Number(value)] || ''
            : attribute(cell, 't') === 'inlineStr' ? nodes(cell, 't').map(part => part.textContent).join('') : value;
        }
        return Array.from(values, value => value || '');
      });
      if (current === version) content.replaceChildren(table(rows));
    };
    select.addEventListener('change', () => render().catch(() => content.replaceChildren(element('p', 'This worksheet cannot be previewed. Download the original to open it.'))));
    wrapper.append(select, content);
    await render();
    return wrapper;
  };
  // Render one PDF page at a time; embedded browsers may lack a native PDF viewer.
  const pdfPreview = async file => {
    const base = new URL('pdfjs/', vendorUrl).href;
    const pdfjs = await import(`${base}pdf.min.mjs`);
    pdfjs.GlobalWorkerOptions.workerSrc = `${base}pdf.worker.min.mjs`;
    const pdf = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()),
      cMapUrl: `${base}cmaps/`, cMapPacked: true, standardFontDataUrl: `${base}standard_fonts/`,
      wasmUrl: `${base}wasm/`, useSystemFonts: true, isEvalSupported: false }).promise;
    const wrapper = element('div', undefined, 'pdf-preview');
    const controls = element('div', undefined, 'd-flex align-items-center justify-content-center gap-2 mb-3');
    const previous = element('button', 'Previous', 'btn btn-falcon-default btn-sm');
    const next = element('button', 'Next', 'btn btn-falcon-default btn-sm');
    const label = element('span', undefined, 'fs-11'); label.setAttribute('role', 'status');
    previous.type = next.type = 'button';
    const content = element('div');
    controls.append(previous, label, next); wrapper.append(controls, content);
    let pageNumber = 1, version = 0;
    const render = async () => {
      const current = ++version;
      previous.disabled = pageNumber === 1; next.disabled = pageNumber === pdf.numPages;
      label.textContent = `Page ${pageNumber} of ${pdf.numPages}`;
      const page = await pdf.getPage(pageNumber);
      const canvas = element('canvas');
      const viewport = page.getViewport({ scale: 1.5 });
      canvas.width = viewport.width; canvas.height = viewport.height;
      canvas.setAttribute('aria-label', `PDF page ${pageNumber}`); canvas.setAttribute('role', 'img');
      await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
      const text = element('p', (await page.getTextContent()).items.map(item => item.str || '').join(' '), 'visually-hidden');
      if (current === version) content.replaceChildren(canvas, text);
    };
    const change = direction => {
      pageNumber = Math.min(pdf.numPages, Math.max(1, pageNumber + direction));
      render().catch(() => content.replaceChildren(element('p', 'This PDF page cannot be previewed. Download the original to open it.')));
    };
    previous.addEventListener('click', () => change(-1)); next.addEventListener('click', () => change(1));
    await render();
    return wrapper;
  };

  document.querySelectorAll('.file-preview').forEach(card => {
    const canvas = card.querySelector('.original-preview');
    const status = card.querySelector('.preview-status');
    const download = card.querySelector('.preview-download');
    const zoom = card.querySelector('.preview-zoom');
    let url, version = 0, scale = 1;
    const showFile = async file => {
      const current = ++version;
      if (url) URL.revokeObjectURL(url);
      url = URL.createObjectURL(file);
      download.href = url; download.download = file.name; download.hidden = false;
      zoom.hidden = true; scale = 1;
      canvas.replaceChildren(element('p', 'Loading preview…', 'p-3 text-600'));
      status.textContent = file.name;
      try {
        const extension = file.name.split('.').pop().toLowerCase();
        let preview;
        if (file.type.startsWith('image/') || /^(jpe?g|png|gif|webp|bmp|avif|svg)$/.test(extension)) {
          preview = element('img'); preview.src = url; preview.alt = file.name;
          preview.className = 'preview-image';
          preview.addEventListener('error', () => { if (current === version) status.textContent = 'This image format is not supported by your browser. Download it to open it.'; });
          zoom.hidden = false;
        } else if (extension === 'pdf' || file.type === 'application/pdf') {
          preview = await pdfPreview(file);
        } else if (extension === 'docx') {
          preview = await wordPreview(file);
          status.textContent = 'Word content preview · layout and embedded images may differ';
        } else if (extension === 'xlsx') {
          preview = await excelPreview(file);
          status.textContent = 'Excel cell preview · cached values, without formatting or charts';
        } else if (extension === 'csv') preview = table(csvRows(await file.text()));
        else if (extension === 'txt' || file.type.startsWith('text/')) preview = element('pre', await file.text(), 'raw-text');
        else preview = element('div', 'This file needs its desktop application. Download the original to view it; DOCX and XLSX content can be previewed here.', 'preview-empty fs-10');
        if (current !== version) return;
        canvas.replaceChildren(preview);
      } catch (error) {
        if (current !== version) return;
        canvas.replaceChildren(element('div', 'Preview unavailable. Download the original to open it.', 'preview-empty'));
        status.textContent = error.message;
      }
    };
    const controller = new AbortController();
    const loadOriginal = async () => {
      try {
        const response = await fetch(card.dataset.fileUrl, { signal: controller.signal, credentials: 'same-origin' });
        if (!response.ok) throw new Error(response.status === 404
          ? 'The original file is no longer available at its storage path.' : 'The original file could not be loaded.');
        const blob = await response.blob();
        await showFile(new File([blob], card.dataset.fileName, { type: blob.type }));
      } catch (error) {
        if (error.name === 'AbortError') return;
        canvas.replaceChildren(element('div', error.message, 'preview-empty fs-10'));
        status.textContent = 'Original file unavailable';
        download.hidden = true;
      }
    };
    loadOriginal();
    zoom.addEventListener('click', event => {
      const button = event.target.closest('[data-zoom]');
      const image = canvas.querySelector('img');
      if (!button || !image) return;
      scale = button.dataset.zoom === 'fit' ? 1 : Math.min(4, Math.max(0.5, scale + (button.dataset.zoom === 'in' ? 0.25 : -0.25)));
      image.style.width = scale === 1 ? '' : `${scale * 100}%`;
      image.style.maxWidth = scale === 1 ? '' : 'none';
      image.style.maxHeight = scale === 1 ? '' : 'none';
    });
    window.addEventListener('pagehide', () => { controller.abort(); if (url) URL.revokeObjectURL(url); });
  });

  const workspace = document.getElementById('review-workspace');
  if (!workspace) return;
  const original = JSON.parse(document.getElementById('markdown-data').textContent);
  const editor = document.getElementById('markdown-editor');
  const status = document.getElementById('draft-status');
  const preview = document.getElementById('markdown-preview');
  const tabs = [document.getElementById('preview-tab'), document.getElementById('source-tab')];
  const value = () => editor ? editor.value : original;
  let submitting = false;
  // Parse Markdown, then rebuild an allowlisted DOM. Never insert unsanitized HTML.
  const renderMarkdown = () => {
    const renderer = new marked.Renderer();
    renderer.html = ({ text }) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    renderer.image = () => '';
    const parsed = new DOMParser().parseFromString(marked.parse(value(), { renderer }), 'text/html');
    const allowed = new Set('P BR H1 H2 H3 H4 H5 H6 STRONG EM DEL CODE PRE UL OL LI TABLE THEAD TBODY TR TH TD BLOCKQUOTE A HR'.split(' '));
    const clean = node => {
      if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.textContent);
      const result = allowed.has(node.nodeName) ? element(node.nodeName.toLowerCase()) : document.createDocumentFragment();
      if (node.nodeName === 'A') {
        const href = node.getAttribute('href') || '';
        try {
          if (/^(https?:|mailto:)$/.test(new URL(href, location.href).protocol)) { result.href = href; result.rel = 'noopener noreferrer'; }
        } catch (_) { /* Invalid links remain readable text. */ }
      }
      for (const child of node.childNodes) result.append(clean(child));
      return result;
    };
    preview.replaceChildren(...[...parsed.body.childNodes].map(clean));
    if (!value().trim()) preview.append(element('p', 'No Markdown was returned for this attempt.', 'text-600'));
  };
  const activate = selected => {
    tabs.forEach(tab => {
      const active = tab === selected;
      tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
      tab.classList.toggle('btn-primary', active); tab.classList.toggle('btn-falcon-default', !active);
      document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
    });
    if (selected === tabs[0]) renderMarkdown();
  };
  tabs.forEach(tab => {
    tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
    tab.addEventListener('click', () => activate(tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[1] : tabs.find(item => item !== tab);
      activate(next); next.focus();
    });
  });
  const compare = document.getElementById('compare-toggle');
  compare.addEventListener('click', () => {
    const expanded = compare.getAttribute('aria-expanded') !== 'true';
    compare.setAttribute('aria-expanded', String(expanded));
    compare.querySelector('span:last-child').textContent = expanded ? 'Hide original' : 'Compare original';
    document.getElementById('source-panel').hidden = !expanded;
    workspace.classList.toggle('is-comparing', expanded);
  });
  if (editor) {
    editor.addEventListener('input', () => { status.textContent = value() === original ? 'No unsaved changes' : 'Unsaved changes'; });
    document.getElementById('markdown-form').addEventListener('submit', () => {
      submitting = true;
      document.getElementById('save-markdown').disabled = true;
      status.textContent = 'Saving Markdown…';
    });
    // Back navigation may restore a form with its submit button still disabled.
    window.addEventListener('pageshow', () => {
      submitting = false;
      document.getElementById('save-markdown').disabled = false;
      status.textContent = value() === original ? 'No unsaved changes' : 'Unsaved changes';
    });
    document.getElementById('reset-markdown').addEventListener('click', () => {
      editor.value = original;
      renderMarkdown(); status.textContent = 'Reset to saved extraction';
    });
    window.addEventListener('beforeunload', event => {
      if (!submitting && value() !== original) { event.preventDefault(); event.returnValue = ''; }
    });
  }
  document.getElementById('download-markdown').addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([value()], { type: 'text/markdown;charset=utf-8' }));
    const link = element('a'); link.href = url;
    link.download = `${workspace.dataset.downloadName.replace(/\.[^.]+$/, '')}.md`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
