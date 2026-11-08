/* mate.js - browser side of the Python port of "Mysql Ajax Table Editor".
 *
 * Replaces js/mate/ajax_table_editor.js + js/local/seistt_functions.js.  No jQuery:
 * the server returns data (not HTML), and every value is inserted with
 * textContent, so database content cannot inject markup.  The only innerHTML use
 * is the developer supplied help text (`help_html` in the editor config).
 */
(function () {
  'use strict';
  const CFG = window.MATE_CONFIG;
  const INSTANCE = CFG.instance;
  const STORE_KEY = 'mate:' + INSTANCE + ':state';

  // ---------------------------------------------------------------- helpers
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'checked' || k === 'selected' || k === 'disabled' || k === 'readOnly') el[k] = !!v;
      else if (k === 'value') el.value = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const $ = (sel, root) => (root || document).querySelector(sel);
  const icon = (name) => h('i', { class: 'glyphicon glyphicon-' + name });
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function appendHighlighted(el, text, needle) {
    if (!needle) { el.append(document.createTextNode(text)); return; }
    const parts = text.split(new RegExp('(' + escRe(needle) + ')', 'ig'));
    parts.forEach((p, i) => {
      if (i % 2 === 1) el.append(h('mark', { text: p }));
      else if (p) el.append(document.createTextNode(p));
    });
  }

  let pending = 0;
  async function api(url, body) {
    pending++; $('#mate-loader').style.display = 'inline';
    try {
      const res = await fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Mate-Request': '1' },
        body: JSON.stringify(body || {}),
      });
      let data = {};
      try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
      if (!res.ok) {
        const err = new Error(data.error || ('Request failed (' + res.status + ')'));
        err.data = data; err.status = res.status; throw err;
      }
      return data;
    } finally {
      if (--pending === 0) $('#mate-loader').style.display = 'none';
    }
  }

  function toast(msg, type, ms) {
    const t = h('div', { class: 'alert alert-' + (type === 'success' ? 'success' : 'danger'), role: 'alert', text: msg });
    $('#mate-toasts').append(t);
    setTimeout(() => t.remove(), ms || 4000);
  }

  // ----------------------------------------------------------------- modal
  function openModal(title, body, buttons, opts) {
    closeModal();
    const size = opts && opts.width && opts.width >= 800 ? ' modal-lg' : (opts && opts.width && opts.width <= 420 ? ' modal-sm' : '');
    const dialog = h('div', { class: 'modal-dialog' + size, role: 'document' },
      h('div', { class: 'modal-content' },
        h('div', { class: 'modal-header' },
          h('button', { type: 'button', class: 'close', 'aria-label': 'Close', onclick: closeModal }, h('span', { 'aria-hidden': 'true' }, '\u00d7')),
          h('h4', { class: 'modal-title', text: title })),
        h('div', { class: 'modal-body' }, body),
        buttons && buttons.length ? h('div', { class: 'modal-footer' }, buttons) : null));
    const modal = h('div', { class: 'modal fade in', tabindex: '-1', role: 'dialog', onmousedown: (e) => { if (e.target === modal) closeModal(); } }, dialog);
    $('#mate-modal-root').append(modal, h('div', { class: 'modal-backdrop fade in' }));
    document.body.classList.add('modal-open');
    const first = dialog.querySelector('input:not([type=hidden]),select,textarea,button.btn-primary');
    if (first) first.focus();
    return modal;
  }
  function closeModal() { $('#mate-modal-root').replaceChildren(); document.body.classList.remove('modal-open'); }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
  const btn = (label, onclick, cls) => h('button', { type: 'button', class: 'btn btn-sm ' + (cls || 'btn-default'), onclick, text: label });

  // ----------------------------------------------------------------- state
  let state = loadState();
  let data = null;
  let L = {};

  function loadState() {
    try {
      const s = JSON.parse(sessionStorage.getItem(STORE_KEY) || 'null');
      if (s && typeof s === 'object') return Object.assign({}, CFG.defaultState, s);
    } catch (_) { /* ignore */ }
    return Object.assign({}, CFG.defaultState);
  }
  function saveState() { try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) { /* ignore */ } }

  async function load(patch) {
    if (patch) { Object.assign(state, patch); }
    try {
      data = await api(CFG.urls.table, { state });
    } catch (e) { toast(e.message); return; }
    state = data.state; saveState();
    L = data.lang;
    render();
  }

  // --------------------------------------------------------------- rendering
  function render() {
    const ui = data.ui;
    document.title = data.title ? data.title + ' - ' + document.title.split(' - ').pop() : document.title;

    // title (+ help)
    const title = $('#mate-title'); title.replaceChildren(document.createTextNode(data.title || ''));
    if (data.help_html) {
      title.append(h('span', { class: 'mate-help text-primary', title: 'Help', onclick: () => {
        const div = h('div'); div.innerHTML = data.help_html;       // trusted, developer supplied
        openModal('Help', div, null, { width: 600 });
      } }, icon('question-sign')));
    }

    // quick search box
    const sbox = $('#' + INSTANCE + 'searchString');
    sbox.placeholder = (L.lblSearch || 'Search') + '...';
    if (document.activeElement !== sbox) sbox.value = state.searchString || '';
    $('#mate-search-form').style.visibility = ui.quick ? 'visible' : 'hidden';

    renderTable();
    $('#mate-records').textContent = ui.record_info ? data.record_text : '';
    renderControls();
    renderAdvanced();
  }

  function colHeader(c) {
    const th = h('th', { class: 'mate-sort', title: c.title || null, style: c.min_width ? 'min-width:' + c.min_width + 'px' : null });
    if (c.distinct) {
      th.append(h('a', { href: '#', title: 'Distinct values', onclick: (e) => { e.preventDefault(); showDistinct(c); } }, icon('list')), ' ');
    }
    const nextDir = c.sorted === 'asc' ? 'desc' : 'asc';
    th.append(h('a', { href: '#', onclick: (e) => { e.preventDefault(); load({ orderByColumn: c.key, ascOrDesc: nextDir }); } }, c.text));
    th.append(' ', icon(c.sorted === 'asc' ? 'chevron-up' : (c.sorted === 'desc' ? 'chevron-down' : 'sort')),);
    if (!c.sorted) th.lastChild.classList.add('text-muted');
    return th;
  }

  // plain clickable icons (no button chrome)
  const iconLink = (name, title, fn, cls) => h('a', { href: '#', class: 'mate-icon ' + (cls || ''), title, 'aria-label': title,
    onclick: (e) => { e.preventDefault(); fn(); } }, icon(name));

  function iconCell(row) {
    const ui = data.ui, rm = (ui.remove_icons || '').toUpperCase();
    const td = h('td', { class: 'mate-icons' });
    if (ui.view && !rm.includes('V')) td.append(iconLink('info-sign', L.ttlInfo, () => viewRow(row.id)));
    if (ui.edit && !rm.includes('E')) td.append(iconLink('pencil', L.ttlEdit, () => editRow(row)));
    if (ui.copy && !rm.includes('C')) td.append(iconLink('duplicate', L.ttlCopy, () => copyRows([row.id])));
    if (ui.delete && !rm.includes('D')) td.append(iconLink('trash', L.ttlDelete, () => deleteRows([row.id]), 'text-danger'));
    return td;
  }

  function renderTable() {
    const ui = data.ui, cols = data.columns;
    const table = h('table', { class: 'mate-table table table-striped table-bordered table-hover table-condensed' });
    const hasIcons = ui.icons && (ui.view || ui.edit || ui.copy || ui.delete);
    const first = hasIcons && ui.icon_position === 'first', last = hasIcons && ui.icon_position === 'last';
    const head = h('tr', { id: 'header_row' });
    if (ui.multi) head.append(h('th', { width: 30 }, h('input', { type: 'checkbox', id: 'select_all', onchange: (e) =>
      table.querySelectorAll('input.row-cb').forEach((cb) => { cb.checked = e.target.checked; }) })));
    if (first) head.append(h('th'));
    cols.forEach((c) => head.append(colHeader(c)));
    if (last) head.append(h('th'));

    let filterRow = null;
    if (ui.filter && cols.some((c) => c.filterable)) {
      filterRow = h('tr', { id: 'filter_row', class: 'mate-filter' });
      if (ui.multi) filterRow.append(h('td'));
      if (first) filterRow.append(h('td'));
      cols.forEach((c) => filterRow.append(h('td', {}, c.filterable ? h('input', {
        type: 'text', class: 'filterInput form-control input-sm', 'data-col': c.key, id: INSTANCE + 'filter_' + c.key,
        placeholder: L.lblFilter || null, value: c.filter || '', onkeyup: (e) => { if (e.key === 'Enter') applyFilters(); } }) : null)));
      if (last) filterRow.append(h('td'));
    }
    const pos = ui.filter_position;
    const thead = h('thead'), tbody = h('tbody');
    if (filterRow && (pos === 'top' || pos === 'top-before')) thead.append(filterRow);
    thead.append(head);
    if (filterRow && pos === 'top-after') thead.append(filterRow);

    data.rows.forEach((row) => {
      const tr = h('tr', { id: 'row_' + row.num, 'data-id': row.id, 'data-num': row.num });
      if (ui.multi) tr.append(h('td', {}, h('input', { type: 'checkbox', class: 'row-cb', value: row.id })));
      if (first) tr.append(iconCell(row));
      row.cells.forEach((cell, i) => tr.append(cellEl(cell, cols[i])));
      if (last) tr.append(iconCell(row));
      tbody.append(tr);
    });
    if (Object.keys(data.totals || {}).length) {
      const tr = h('tr', { class: 'info' });
      if (ui.multi) tr.append(h('td'));
      if (first) tr.append(h('td'));
      cols.forEach((c) => tr.append(h('td', { class: 'mate-right' }, h('strong', {}, data.totals[c.key] !== undefined ? String(data.totals[c.key]) : ''))));
      tbody.append(tr);
    }
    table.append(thead, tbody);
    if (filterRow && !['top', 'top-before', 'top-after'].includes(pos)) tbody.append(filterRow);

    const wrap = $('#mate-table');
    wrap.replaceChildren(h('div', { class: 'table-responsive' }, table));
    if (!data.rows.length) wrap.append(h('div', { class: 'panel-body' }, h('p', { class: 'text-center text-muted' }, L.ttlNoRecord)));
  }

  function cellEl(cell, col) {
    const td = h('td', { class: cell.a === 'right' ? 'mate-right' : null });
    if (cell.o) {
      td.append(h('select', { class: 'form-control input-sm' }, cell.o.map((o) => h('option', { text: o }))));
    } else if (cell.t !== '') {
      const holder = cell.title ? h('span', { class: 'mate-trunc', title: cell.title }) : td;
      if (data.ui.highlight) appendHighlighted(holder, cell.t, state.searchString);
      else holder.append(document.createTextNode(cell.t));
      if (holder !== td) td.append(holder);
    }
    return td;
  }

  // ---------------------------------------------------------- bottom controls
  function renderControls() {
    const ui = data.ui, pg = data.paging, box = $('#mate-controls');
    const parts = [];
    const sel = (label, options, onchange) => h('div', { class: 'form-inline' }, h('div', { class: 'form-group' },
      h('label', { class: 'control-label small', text: label + ' ' }), h('select', { class: 'form-control input-sm', onchange }, options)));
    if (ui.pagination_links) {
      if (pg.num_pages > 1) {
        parts.push(h('ul', { class: 'pagination pagination-sm', style: 'margin:0 6px 6px 0; vertical-align:top' }, pg.links.map((p) =>
          h('li', { class: p.active ? 'active' : null },
            h('a', { href: '#', onclick: (e) => { e.preventDefault(); load({ start: p.start }); } }, String(p.label))))));
      }
    } else {
      parts.push(sel(L.lblPage, pg.dropdown.map((p) => h('option', { value: p.start, selected: p.active, text: p.label })),
        (e) => load({ start: parseInt(e.target.value, 10) })));
    }
    if (ui.display_num) {
      parts.push(sel(L.lblDisplay, pg.display_num_options.map((n) => h('option', { value: n, selected: n === data.state.displayNum, text: n })),
        (e) => load({ displayNum: parseInt(e.target.value, 10), start: 0 })));
    }
    const group = [];
    if (ui.add) group.push(btn(L.btnAdd, addRow, 'btn-success'));
    if (!ui.icons && ui.edit) group.push(btn(L.btnEdit, () => withSelected(1, (ids) => editRow(rowById(ids[0])))));
    if (!ui.icons && ui.view) group.push(btn(L.btnView, () => withSelected(1, (ids) => viewRow(ids[0]))));
    if (!ui.icons && ui.copy) group.push(btn(L.btnCopy, () => withSelected(0, copyRows)));
    if (!ui.icons && ui.delete) group.push(btn(L.btnDelete, () => withSelected(0, deleteRows), 'btn-danger'));
    if (group.length) parts.push(h('div', { class: 'btn-group', role: 'group' }, group));
    const tools = [];
    if (ui.export) tools.push(btn(L.btnExport, exportCsv));
    if (ui.hide) tools.push(btn(L.btnShowHide, showHideDialog));
    if (ui.order) tools.push(btn(L.btnOrderCols, orderDialog));
    if (tools.length) parts.push(h('div', { class: 'btn-group', role: 'group' }, tools));
    if (ui.filter && ui.display_filter_btns) {
      parts.push(h('div', { class: 'btn-group', role: 'group' },
        btn(L.btnFilters, applyFilters, 'btn-info'), btn(L.btnCFilters, () => load({ filterSearches: {}, start: 0 }))));
    }
    if (ui.advanced && state.searchType === 'quick') {
      parts.push(btn(L.btnASearch, () => load({ searchType: 'advanced', searchString: '', numAdvSearches: 3, start: 0 })));
    } else if (ui.quick && state.searchType === 'advanced') {
      parts.push(btn(L.btnQSearch, () => load({ searchType: 'quick', advSearches: [], start: 0 })));
    }
    box.replaceChildren(...parts);
  }

  function rowById(id) { return data.rows.find((r) => String(r.id) === String(id)); }
  function selectedIds() { return [...document.querySelectorAll('input.row-cb:checked')].map((c) => c.value); }
  function withSelected(exactly, fn) {
    const ids = selectedIds();
    if (!ids.length || (exactly && ids.length !== exactly)) { toast(exactly ? L.edit1Row : '\u2014', 'error'); return; }
    fn(ids);
  }

  function applyFilters() {
    const f = {};
    document.querySelectorAll('#filter_row input.filterInput').forEach((i) => { if (i.value) f[i.dataset.col] = i.value; });
    load({ filterSearches: f, start: 0 });
  }

  function exportCsv() {
    const b64 = btoa(unescape(encodeURIComponent(JSON.stringify(state))));
    window.location.href = CFG.urls.exportCsv + '?session_data=' + encodeURIComponent(b64);
  }

  // ------------------------------------------------------------- advanced search
  function renderAdvanced() {
    const root = $('#mate-adv');
    if (!(data.ui.advanced && state.searchType === 'advanced')) { root.replaceChildren(); return; }
    const n = state.numAdvSearches || 3, saved = state.advSearches || [];
    const rows = [];
    for (let i = 0; i < n; i++) {
      const s = saved[i] || {};
      rows.push(h('div', { class: 'form-inline mate-adv-row', style: 'margin-bottom:8px' },
        h('select', { 'data-f': 'cols', class: 'form-control input-sm' },
          h('option', { value: '', text: L.lblSelect }),
          data.adv.columns.map((c) => h('option', { value: c.key, selected: s.cols === c.key, text: c.text }))), ' ',
        h('select', { 'data-f': 'opts', class: 'form-control input-sm' },
          data.adv.operators.map((o) => h('option', { value: o.sign, selected: s.opts === o.sign, text: o.text }))), ' ',
        h('input', { 'data-f': 'strs', type: 'text', class: 'form-control input-sm', size: 28, value: s.strs || '',
          onkeyup: (e) => { if (e.key === 'Enter') runAdvanced(false); } })));
    }
    const body = h('div', { class: 'panel-body', id: 'adv_box' }, rows);
    if (!data.ui.remove_criteria) {
      body.append(h('div', { style: 'margin-bottom:8px' }, h('strong', { text: L.lblMatch + ' ' }),
        h('label', { class: 'radio-inline' }, h('input', { type: 'radio', name: 'match', checked: state.matchAll !== false,
          onchange: () => { state.matchAll = true; saveState(); } }), L.lblAllCrit),
        h('label', { class: 'radio-inline' }, h('input', { type: 'radio', name: 'match', checked: state.matchAll === false,
          onchange: () => { state.matchAll = false; saveState(); } }), L.lblAnyCrit)));
    }
    body.append(h('div', { class: 'btn-group' },
      btn(L.lblSearch, () => runAdvanced(false), 'btn-primary'),
      btn(L.btnAddCrit, () => runAdvanced(true)),
      btn(L.btnCSearch, () => load({ matchAll: true, numAdvSearches: 3, advSearches: [], start: 0 }))));
    root.replaceChildren(h('div', { class: 'panel panel-primary' },
      h('div', { class: 'panel-heading' }, h('h3', { class: 'panel-title', text: L.btnASearch })), body));
  }

  function runAdvanced(addCriteria) {
    const list = [...document.querySelectorAll('#adv_box .mate-adv-row')].map((d) => ({
      cols: d.querySelector('[data-f=cols]').value, opts: d.querySelector('[data-f=opts]').value,
      strs: d.querySelector('[data-f=strs]').value,
    }));
    load({ advSearches: list, numAdvSearches: (state.numAdvSearches || 3) + (addCriteria ? 1 : 0), start: 0 });
  }

  // ---------------------------------------------------------------- dialogs
  async function viewRow(id) {
    try {
      const d = await api(CFG.urls.view, { id });
      const table = h('table', { class: 'table table-striped table-bordered table-condensed' });
      d.fields.forEach((f) => {
        const cell = h('td');
        const v = f.value;
        if (f.options) cell.append(h('select', { class: 'form-control input-sm' }, f.options.map((o) => h('option', { text: o }))));
        else if (v.length > 40) cell.append(h('span', { class: 'mate-trunc', title: v, text: v.slice(0, 40) + '...' }));
        else cell.append(v);
        table.append(h('tr', {}, h('th', { class: 'text-right', style: 'width:40%', text: f.label }), cell));
      });
      openModal(d.title, table, [btn(L.btnCancel, closeModal)], { width: 560 });
    } catch (e) { toast(e.message); }
  }

  function inputEl(spec, idPrefix) {
    const id = idPrefix + spec.key;
    const common = { id, name: spec.key, 'data-key': spec.key, readOnly: spec.readonly };
    let el;
    switch (spec.type) {
      case 'select': {
        el = h('select', Object.assign({ class: 'form-control input-sm' }, common),
          spec.allow_blank ? h('option', { value: '', text: L.lblSelect }) : null,
          spec.options.map((o) => h('option', { value: o.value, selected: String(o.value) === String(spec.value), text: o.label })));
        break;
      }
      case 'radio':
        el = h('span', { id, 'data-key': spec.key, 'data-radio': '1' }, spec.options.map((o) =>
          h('label', { class: 'radio-inline' },
            h('input', { type: 'radio', name: id, value: o.value, checked: String(o.value) === String(spec.value) }), o.label)));
        break;
      case 'textarea':
        el = h('textarea', Object.assign({ class: 'form-control', rows: spec.rows }, common), String(spec.value ?? ''));
        break;
      case 'checkbox':
        el = h('input', Object.assign({ type: 'checkbox', checked: String(spec.value) === String(spec.checked_value),
          'data-checked': spec.checked_value, 'data-unchecked': spec.unchecked_value }, common));
        break;
      case 'hidden':
        el = h('input', Object.assign({ type: 'hidden', value: spec.value }, common));
        break;
      default:
        el = h('input', Object.assign({ type: spec.type === 'date' ? 'date' : (spec.type || 'text'),
          class: 'form-control input-sm', value: spec.value ?? '', maxlength: spec.maxlen || null }, common));
    }
    return el;
  }

  function readInput(el) {
    if (el.dataset.radio) { const c = el.querySelector('input:checked'); return c ? c.value : ''; }
    if (el.type === 'checkbox') return el.checked ? el.dataset.checked : el.dataset.unchecked;
    return el.value;
  }
  function collect(root) {
    const out = {};
    root.querySelectorAll('[data-key]').forEach((el) => { if (!el.readOnly || el.type === 'hidden') out[el.dataset.key] = readInput(el); });
    return out;
  }
  function markErrors(root, err) {
    root.querySelectorAll('.has-error').forEach((e) => e.classList.remove('has-error'));
    (err.data && err.data.invalid_fields || []).forEach((k) => {
      const el = root.querySelector('[data-key="' + k + '"]'); if (el) (el.closest('.form-group, td') || el.parentElement).classList.add('has-error');
    });
  }

  // in-place editing -------------------------------------------------------
  async function editRow(row) {
    if (!data.ui.edit_in_place) return editRowModal(row.id);
    const tr = document.querySelector('tr[data-id="' + CSS.escape(String(row.id)) + '"]');
    if (!tr || tr.classList.contains('mate-editing')) return;
    try {
      const form = await api(CFG.urls.editForm, { id: row.id });
      const byKey = Object.fromEntries(form.inputs.map((i) => [i.key, i]));
      const offset = (data.ui.multi ? 1 : 0) + (data.ui.icons && data.ui.icon_position === 'first' ? 1 : 0);
      data.columns.forEach((c, i) => {
        const spec = byKey[c.key];
        if (spec && spec.type !== 'hidden') tr.children[offset + i].replaceChildren(inputEl(spec, INSTANCE + 'e' + row.num + '_'));
      });
      tr.classList.add('mate-editing');
      const td = tr.querySelector('td.mate-icons');
      if (td) td.replaceChildren(
        iconLink('ok', L.btnUpdate, () => saveInPlace(tr, row), 'text-success'),
        iconLink('remove', L.btnCancel, () => load()));
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') saveInPlace(tr, row); });
    } catch (e) { toast(e.message); }
  }

  async function saveInPlace(tr, row) {
    const values = {};
    tr.querySelectorAll('[data-key]').forEach((el) => { if (!el.readOnly) values[el.dataset.key] = readInput(el); });
    try {
      await api(CFG.urls.update, { id: row.id, values, in_place: true, row_num: row.num });
      await load();
    } catch (e) { markErrors(tr, e); toast(e.message); }
  }

  async function editRowModal(id) {
    try {
      const form = await api(CFG.urls.editForm, { id });
      showForm(form, async (values, root) => {
        try { await api(CFG.urls.update, { id, values }); closeModal(); await load(); }
        catch (e) { markErrors(root, e); toast(e.message); }
      }, L.btnUpdate);
    } catch (e) { toast(e.message); }
  }

  async function addRow() {
    try {
      const form = await api(CFG.urls.addForm, {});
      showForm(form, async (values, root) => {
        try { await api(CFG.urls.insert, { values }); closeModal(); await load(); }
        catch (e) { markErrors(root, e); toast(e.message); }
      }, L.btnAdd);
    } catch (e) { toast(e.message); }
  }

  function showForm(form, onSubmit, label) {
    const root = h('form', { class: 'form-horizontal', onsubmit: (e) => e.preventDefault() });
    form.inputs.forEach((spec) => {
      const el = inputEl(spec, INSTANCE + 'f_');
      if (spec.type === 'hidden') { root.append(el); return; }
      if (spec.type === 'checkbox') el.classList.remove('form-control');
      root.append(h('div', { class: 'form-group' },
        h('label', { class: 'col-sm-4 control-label', for: el.id }, spec.label, spec.required ? h('span', { class: 'text-danger', text: ' ' + data.ui.req_marker }) : null),
        h('div', { class: 'col-sm-8' }, el)));
    });
    openModal(form.title, root, [
      btn(label, () => onSubmit(collect(root), root), 'btn-primary'), btn(L.btnCancel, closeModal)], { width: 600 });
    root.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') { e.preventDefault(); onSubmit(collect(root), root); } });
  }

  async function deleteRows(ids) {
    if (!confirm(L.ttlDelete + '?')) return;
    try { await api(CFG.urls.del, { ids }); await load(); } catch (e) { toast(e.message); }
  }
  async function copyRows(ids) {
    try { await api(CFG.urls.copy, { ids }); await load(); } catch (e) { toast(e.message); }
  }

  async function showDistinct(c) {
    try {
      const d = await api(CFG.urls.distinct, { state, col: c.key });
      const list = h('div', { class: 'list-group' }, d.values.map((v) => h('a', { href: '#', class: 'list-group-item', onclick: (e) => {
        e.preventDefault(); closeModal();
        load({ filterSearches: Object.assign({}, state.filterSearches, { [c.key]: String(v.value ?? '') }), start: 0 });
      } }, (v.value === null ? '' : String(v.value)), h('span', { class: 'badge', text: v.count }))));
      openModal('Select a distinct value to filter on', list, [btn(L.btnCancel, closeModal)], { width: 420 });
    } catch (e) { toast(e.message); }
  }

  // show/hide + order columns ------------------------------------------------
  async function showHideDialog() {
    try {
      const s = await api(CFG.urls.columns, {});
      const box = h('div', {}, s.hide.map((c) => h('div', { class: 'checkbox' },
        h('label', {}, h('input', { type: 'checkbox', 'data-col': c.key, checked: c.visible }), c.text))));
      openModal(s.show_hide_title, box, [
        btn(L.btnUpdate, async () => {
          const visible = {}; box.querySelectorAll('input[data-col]').forEach((i) => { visible[i.dataset.col] = i.checked; });
          try { await api(CFG.urls.columnsSave, { visible }); closeModal(); await load(); } catch (e) { toast(e.message); }
        }, 'btn-primary'), btn(L.btnCancel, closeModal)], { width: 420 });
    } catch (e) { toast(e.message); }
  }

  async function orderDialog() {
    try {
      const s = await api(CFG.urls.columns, {});
      const list = h('ul', { class: 'list-group' });
      const mkItem = (c) => {
        const li = h('li', { class: 'list-group-item mate-order-item', draggable: 'true', 'data-col': c.key },
          h('span', { text: c.text }),
          h('span', { class: 'btn-group btn-group-xs' },
            h('button', { type: 'button', class: 'btn btn-default', title: 'Up', onclick: () => { if (li.previousElementSibling) list.insertBefore(li, li.previousElementSibling); } }, icon('arrow-up')),
            h('button', { type: 'button', class: 'btn btn-default', title: 'Down', onclick: () => { if (li.nextElementSibling) list.insertBefore(li.nextElementSibling, li); } }, icon('arrow-down'))));
        li.addEventListener('dragstart', () => li.classList.add('dragging'));
        li.addEventListener('dragend', () => li.classList.remove('dragging'));
        return li;
      };
      s.order.forEach((c) => list.append(mkItem(c)));
      list.addEventListener('dragover', (e) => {
        e.preventDefault();
        const dragging = list.querySelector('.dragging'); if (!dragging) return;
        const after = [...list.querySelectorAll('.mate-order-item:not(.dragging)')].find((el) => e.clientY <= el.getBoundingClientRect().top + el.offsetHeight / 2);
        list.insertBefore(dragging, after || null);
      });
      openModal(s.order_title, list, [
        btn(L.btnUpdate, async () => {
          const order = [...list.querySelectorAll('li')].map((li) => li.dataset.col);
          try { await api(CFG.urls.columnsSave, { order }); closeModal(); await load(); } catch (e) { toast(e.message); }
        }, 'btn-primary'),
        btn(L.btnReset, async () => { try { await api(CFG.urls.columnsSave, { reset_order: true }); closeModal(); await load(); } catch (e) { toast(e.message); } }),
        btn(L.btnCancel, closeModal)], { width: 460 });
    } catch (e) { toast(e.message); }
  }

  // ------------------------------------------------------------------- boot
  $('#mate-search-form').addEventListener('submit', (e) => {
    e.preventDefault();
    load({ searchType: 'quick', searchString: $('#' + INSTANCE + 'searchString').value, start: 0 });
  });
  $('#mate-clear-search').addEventListener('click', () => {
    $('#' + INSTANCE + 'searchString').value = '';
    load({ searchString: '', start: 0 });
  });
  load();
})();
