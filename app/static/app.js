const $ = (selector) => document.querySelector(selector);
const KIND = {oem: 'OEM', aftermarket: 'Аналог', standard: 'Стандарт'};
const STATUS = {ok: 'Найдено', not_found: 'Нет совпадений', blocked: 'Недоступен', error: 'Ошибка', no_sources: 'Нет каталогов', pending: 'В очереди', running: 'Обрабатывается', done: 'Завершено', failed: 'Ошибка задания'};
const state = {crosses: [], sources: new Map(), busy: false, uploading: false, jobsBusy: false, limit: 2, active: false, jobsJSON: '', file: null, mode: 'empty', selectedJob: null, jobVersion: '', viewRequest: 0, page: 1};

// All untrusted values are text nodes, including catalogue data and filenames.
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notice(selector, text = '', error = false) {
  const node = $(selector);
  node.textContent = text;
  node.classList.toggle('error', error);
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {...options, signal: AbortSignal.timeout(90000)}); }
  catch (error) { throw new Error(error.name === 'TimeoutError' ? 'Сервер не ответил вовремя. Обновите историю перед повторной загрузкой.' : 'Нет соединения с сервером. Проверьте сеть и повторите.'); }
  if (response.status === 401) { location.assign('/login'); throw new Error('Сессия завершена. Войдите снова.'); }
  if (!response.ok) {
    const messages = {413: 'Файл слишком большой. Максимум — 20 МБ.', 422: 'Проверьте заполнение полей и формат номера.', 429: 'Слишком много запросов. Подождите минуту и повторите.'};
    let detail;
    if ([400, 429].includes(response.status)) { try { detail = (await response.json()).detail; } catch (_) { /* generic fallback */ } }
    throw new Error(messages[response.status] || (typeof detail === 'string' ? detail : 'Сервис временно недоступен. Повторите позже.'));
  }
  return response.json();
}
function sourceTitle(key) { return state.sources.get(key)?.title || key; }
function canonicalNumber(value) { return String(value || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase(); }

// Accessible account disclosure; logout stays a native POST form.
const profileToggle = $('#profile-toggle');
const profileDropdown = $('#profile-dropdown');
function closeProfile(restoreFocus = false) {
  profileDropdown.hidden = true;
  profileToggle.setAttribute('aria-expanded', 'false');
  if (restoreFocus) profileToggle.focus();
}
profileToggle.onclick = () => {
  const open = profileDropdown.hidden;
  profileDropdown.hidden = !open;
  profileToggle.setAttribute('aria-expanded', String(open));
};
document.addEventListener('click', event => {
  if (!event.target.closest('.account')) closeProfile();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !profileDropdown.hidden) { closeProfile(true); event.preventDefault(); }
});
document.addEventListener('focusin', event => {
  if (!event.target.closest('.account')) closeProfile();
});

const GROUP_EXAMPLES = {
  brake_pads: ['Колодки', '58101H5A25'], brake_discs: ['Диски', '1K0615301AA'],
  brake_hoses: ['Шланги', '1K0611701K'], shock_absorbers: ['Амортизаторы', '4851080378'],
  radiators: ['Радиаторы', '8200735038'],
};
const SOURCE_LOGOS = {sbparts:'sbparts.svg', brembo:'brembo.svg', trialli:'trialli.svg', brixo:'brixo.svg', luzar:'luzar.svg', nissens:'nissens.svg', kyb:'kyb.png', hola:'hola.svg', brannor:'brannor.svg', hel:'hel.png'};
// One styled, keyboard-operated category list; native select retains the value.
const groupSelect = $('#group');
const groupPicker = el('div', undefined, 'group-picker');
const groupTrigger = el('button', 'Все группы', 'group-trigger');
groupTrigger.type = 'button'; groupTrigger.id = 'group-trigger';
groupTrigger.setAttribute('role', 'combobox');
groupTrigger.setAttribute('aria-haspopup', 'listbox');
groupTrigger.setAttribute('aria-expanded', 'false');
groupTrigger.setAttribute('aria-controls', 'group-options');
const groupOptions = el('div', undefined, 'group-options');
groupOptions.id = 'group-options'; groupOptions.setAttribute('role', 'listbox');
groupOptions.setAttribute('aria-label', 'Товарная группа'); groupOptions.hidden = true;
groupSelect.after(groupPicker); groupPicker.append(groupTrigger, groupOptions);
groupSelect.hidden = true; groupSelect.labels[0].htmlFor = 'group-trigger';
let groupActive = 0;
function syncPicker() {
  groupTrigger.textContent = groupSelect.selectedOptions[0]?.textContent || 'Все группы';
  groupOptions.replaceChildren(...[...groupSelect.options].map((option, index) => {
    const row = el('div', option.textContent, 'group-option'); row.id = `group-option-${index}`;
    row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(option.selected));
    row.onmousedown = event => event.preventDefault();
    row.onclick = () => chooseGroup(index);
    return row;
  }));
}
function closeGroups() {
  groupOptions.hidden = true; groupTrigger.setAttribute('aria-expanded', 'false');
  groupTrigger.removeAttribute('aria-activedescendant');
}
function activateGroup(index) {
  groupActive = Math.max(0, Math.min(groupSelect.options.length - 1, index));
  [...groupOptions.children].forEach((row, i) => row.classList.toggle('active', i === groupActive));
  const row = groupOptions.children[groupActive];
  if (row) { groupTrigger.setAttribute('aria-activedescendant', row.id); row.scrollIntoView({block:'nearest'}); }
}
function openGroups() {
  syncPicker(); groupOptions.hidden = false; groupTrigger.setAttribute('aria-expanded', 'true');
  activateGroup(Math.max(0, groupSelect.selectedIndex));
}
function chooseGroup(index) {
  groupSelect.selectedIndex = index; groupSelect.dispatchEvent(new Event('change', {bubbles:true})); closeGroups(); groupTrigger.focus();
}
groupTrigger.onclick = () => groupOptions.hidden ? openGroups() : closeGroups();
groupTrigger.onkeydown = event => {
  if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
    event.preventDefault(); const wasClosed = groupOptions.hidden;
    if (wasClosed) openGroups();
    if (event.key === 'Home') activateGroup(0);
    else if (event.key === 'End') activateGroup(groupSelect.options.length - 1);
    else if (!wasClosed) activateGroup(groupActive + (event.key === 'ArrowDown' ? 1 : -1));
  } else if (['Enter',' '].includes(event.key)) {
    event.preventDefault(); groupOptions.hidden ? openGroups() : chooseGroup(groupActive);
  } else if (event.key === 'Escape' && !groupOptions.hidden) { event.preventDefault(); closeGroups(); }
  else if (event.key === 'Tab') closeGroups();
};
document.addEventListener('click', event => { if (!groupPicker.contains(event.target)) closeGroups(); });
document.addEventListener('focusin', event => { if (!groupPicker.contains(event.target)) closeGroups(); });
syncPicker();

function syncExamples() {
  syncPicker();
  for (const button of $('#group-choices').children) {
    button.setAttribute('aria-pressed', String(button.dataset.group === $('#group').value && button.dataset.number === $('#oe').value));
  }
}
$('#group').onchange = syncExamples;
$('#oe').oninput = () => { $('#group').value = ''; syncExamples(); };
function groupChoice(group) {
  const example = GROUP_EXAMPLES[group.group];
  if (!example) return null;
  const [title, number] = example;
  const button = el('button', `${title} · ${number}`, 'group-example');
  button.type = 'button'; button.dataset.group = group.group; button.dataset.number = number;
  button.title = `Подставить ${number}`; button.setAttribute('aria-label', `Подставить ${number}`);
  button.onclick = () => { $('#oe').value = number; $('#group').value = group.group; syncExamples(); $('#oe').focus(); };
  return button;
}
function catalogCard(source) {
  let url;
  try { const parsed = new URL(source.homepage); if (['https:', 'http:'].includes(parsed.protocol)) url = parsed; } catch (_) {}
  const title = source.title.replace(/\s*\([^()]*\)\s*$/, '');
  const card = el(url ? 'a' : 'span', undefined, 'catalog-card');
  card.title = source.title;
  const logo = SOURCE_LOGOS[source.key];
  if (logo) {
    const img = el('img'); img.src = `/static/images/brands/${logo}`; img.alt = title;
    img.onerror = () => card.replaceChildren(el('strong', title, 'catalog-brand'));
    card.append(img);
  } else card.append(el('strong', title, 'catalog-brand'));
  if (url) { card.href = url.href; card.target = '_blank'; card.rel = 'noopener noreferrer'; card.setAttribute('aria-label', `${title} — открыть каталог`); }
  return card;
}
async function loadGroups() {
  try {
    const [coverage, sources] = await Promise.all([api('/api/v1/groups'), api('/api/v1/sources')]);
    state.sources = new Map(sources.sources.map(source => [source.key, source]));
    const selected = $('#group').value;
    $('#group').replaceChildren(new Option('Все группы', ''));
    $('#group-choices').replaceChildren();
    for (const group of coverage.groups) {
      $('#group').append(new Option(group.title, group.group));
      const example = groupChoice(group); if (example) $('#group-choices').append(example);
    }
    const enabled = sources.sources.filter(source => sources.default.includes(source.key));
    $('#coverage').replaceChildren(...enabled.map(catalogCard));
    $('#catalogue-count').textContent = `Подключено: ${enabled.length}`;
    $('#group').value = selected;
    if ($('#group').selectedIndex < 0) $('#group').value = '';
    syncExamples(); $('#group-choices').hidden = !$('#group-choices').children.length;
    $('#retry-groups').hidden = true;
    if (state.crosses.length) renderRows();
  } catch (error) { $('#coverage').textContent = error.message; $('#retry-groups').hidden = false; }
}
$('#retry-groups').onclick = loadGroups;
async function loadQuota() {
  try { const quota = await api('/api/v1/account'); $('#quota').replaceChildren(el('span', 'Поисков осталось'), el('strong', String(quota.remaining))); $('#quota').title = `Осталось ${quota.remaining} из ${quota.limit} поисков`; }
  catch (_) { $('#quota').hidden = true; }
}
function clearResult() {
  state.crosses = []; state.lookup = null; state.page = 1; $('#result-pages').replaceChildren();
  $('#result-rows').replaceChildren(); $('#result-table').hidden = true; $('#result-tools').hidden = true;
  $('#result-empty').hidden = true; $('#result-filter').value = ''; $('#filter-count').textContent = '';
  $('#result-count').textContent = ''; $('#result-query').textContent = '';
  $('#btn-export-lookup').hidden = true; $('#job-export').hidden = true;
  $('#source-details').hidden = true; $('#job-details').hidden = true;
}
function highlightJob() {
  for (const row of $('#jobs').children) row.classList.toggle('selected', row.dataset.job === state.selectedJob);
}
$('#lookup-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy) return;
  const oe = $('#oe').value.trim();
  if (oe.length < 2) { notice('#lookup-status', 'Введите хотя бы два символа номера.', true); $('#oe').focus(); return; }
  state.busy = true; state.mode = 'lookup'; state.selectedJob = null; highlightJob();
  const request = ++state.viewRequest;
  const group = $('#group').value || null;
  const groupTitle = $('#group').selectedOptions[0].textContent;
  clearResult(); $('#results-title').textContent = 'Результаты поиска'; $('#result-summary').textContent = 'Проверяем подключённые каталоги…';
  $('#btn-lookup').disabled = true; $('#btn-lookup').textContent = 'Ищем…'; $('#lookup-form').setAttribute('aria-busy','true');
  notice('#lookup-status', 'Поиск может занять около минуты.');
  try {
    const data = await api('/api/v1/lookup', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({oe, group})});
    if (request !== state.viewRequest) return;
    state.lookup = {oe: data.oe, group, groupTitle}; state.crosses = data.crosses;
    const answered = data.sources.filter(s => ['ok','not_found'].includes(s.status));
    const unavailable = data.sources.filter(s => ['error','blocked'].includes(s.status));
    let summary;
    if (data.status === 'no_sources' || !data.sources.length) summary = 'Для этой группы нет подключённых каталогов. Выберите другую группу.';
    else if (!answered.length) summary = 'Каталоги не ответили. Наличие аналогов проверить не удалось. Повторите поиск позже.';
    else if (unavailable.length) summary = `Неполный результат: ответили ${answered.length} из ${data.sources.length} каталогов. Часть источников недоступна.`;
    else if (!data.crosses.length) summary = 'В проверенных каталогах совпадений нет. Проверьте номер и товарную группу.';
    else summary = '';
    $('#result-summary').textContent = summary;
    $('#result-query').textContent = `${data.oe} · ${groupTitle}`;
    $('#source-reports').replaceChildren(...data.sources.map(source => el('span', `${sourceTitle(source.source).replace(/\s*\([^()]*\)\s*$/, '')}: ${STATUS[source.status] || source.status}`, `badge ${['error','blocked'].includes(source.status)?'warning':'neutral'}`)));
    $('#source-summary').textContent = `Каталоги: ${answered.length} из ${data.sources.length}`;
    $('#source-details').hidden = !unavailable.length; $('#source-details').open = Boolean(unavailable.length);
    $('#btn-export-lookup').hidden = !data.crosses.length;
    renderRows(); loadQuota(); notice('#lookup-status');
  } catch (error) { if (request === state.viewRequest) { notice('#lookup-status', error.message, true); $('#result-summary').textContent = error.message; } }
  finally { state.busy = false; $('#btn-lookup').disabled = false; $('#btn-lookup').textContent = 'Найти'; $('#lookup-form').removeAttribute('aria-busy'); }
});
function renderRows() {
  const query = $('#result-filter').value.trim().toLocaleLowerCase();
  const rows = state.crosses.filter(c => `${c.oe_number || state.lookup?.oe || ''} ${c.brand} ${c.number} ${(c.sources || []).map(sourceTitle).join(' ')}`.toLocaleLowerCase().includes(query));
  $('#result-count').textContent = state.crosses.length ? `${state.crosses.length} номеров` : '';
  $('#result-tools').hidden = !state.crosses.length; $('#result-table').hidden = false;
  const totalPages = Math.max(1, Math.ceil(rows.length / 12));
  state.page = Math.max(1, Math.min(state.page, totalPages));
  const start = (state.page - 1) * 12;
  $('#filter-count').textContent = rows.length ? `Показано ${start + 1}–${Math.min(start + 12, rows.length)} из ${rows.length}` : '';
  const pages = $('#result-pages'); pages.replaceChildren();
  if (totalPages > 1) {
    const numbers = el('div', undefined, 'page-numbers'); pages.append(numbers);
    const go = target => {
      state.page = target; renderRows(); $('#result-table').scrollTop = 0;
      pages.querySelector('[aria-current]')?.focus({preventScroll:true});
    };
    const addPage = (label, target, disabled = false) => {
      const button = el('button', label); button.type = 'button'; button.disabled = disabled;
      button.setAttribute('aria-label', label === '‹' ? 'Предыдущая страница' : label === '›' ? 'Следующая страница' : `Страница ${target}`);
      if (label === String(state.page)) button.setAttribute('aria-current', 'page');
      button.onclick = () => go(target); numbers.append(button);
    };
    addPage('‹', state.page - 1, state.page === 1);
    const visible = totalPages <= 7 ? Array.from({length:totalPages}, (_, i) => i + 1)
      : [...new Set([1, state.page - 1, state.page, state.page + 1, totalPages])].filter(n => n >= 1 && n <= totalPages).sort((a,b) => a-b);
    visible.forEach((n, i) => {
      if (i && n - visible[i-1] > 1) {
        const gap = el('button', '…'); gap.type = 'button'; gap.title = 'Перейти на любую страницу';
        gap.setAttribute('aria-label', 'Выбрать страницу');
        gap.onclick = () => { jumpInput.focus(); jumpInput.select(); };
        numbers.append(gap);
      }
      addPage(String(n), n);
    });
    addPage('›', state.page + 1, state.page === totalPages);
    const jump = el('form', undefined, 'page-jump');
    const label = el('label', 'Страница'); label.htmlFor = 'page-number';
    const jumpInput = el('input'); jumpInput.id = 'page-number'; jumpInput.type = 'number';
    jumpInput.min = '1'; jumpInput.max = String(totalPages); jumpInput.step = '1'; jumpInput.required = true;
    jumpInput.inputMode = 'numeric'; jumpInput.value = String(state.page);
    jumpInput.setAttribute('aria-label', 'Перейти на страницу');
    jumpInput.setAttribute('aria-describedby', 'page-total');
    const total = el('span', `из ${totalPages}`); total.id = 'page-total';
    const submit = el('button', 'Перейти'); submit.type = 'submit'; submit.className = 'page-go';
    jump.onsubmit = event => {
      event.preventDefault();
      const target = jumpInput.valueAsNumber;
      if (jump.reportValidity() && Number.isInteger(target) && target >= 1 && target <= totalPages) go(target);
    };
    jump.append(label, jumpInput, total, submit); pages.append(jump);
  }
  $('#result-rows').replaceChildren(...rows.slice(start, start + 12).map((cross, index) => {
    const row = el('tr'); const number = el('td'); number.append(el('code', canonicalNumber(cross.number)));
    const brand = el('td', cross.brand || '—');
    row.append(el('td', String(start + index + 1)), el('td', cross.oe_number || state.lookup?.oe || '—'), brand, number, el('td', (cross.sources || []).map(key => sourceTitle(key).replace(/\s*\([^()]*\)\s*$/, '')).join(', ') || '—'));
    return row;
  }));
  if (!rows.length) { const row = el('tr'); const cell = el('td', state.crosses.length ? 'По этому фильтру нет записей.' : 'Нет номеров для отображения. Статус проверки указан выше.'); cell.colSpan = 5; row.append(cell); $('#result-rows').append(row); }
}
$('#result-filter').oninput = () => { state.page = 1; renderRows(); };
$('#btn-export-lookup').onclick = async () => {
  if (!state.lookup || !state.crosses.length) return;
  const button = $('#btn-export-lookup'); button.disabled = true; button.textContent = 'Готовим Excel…';
  const lookup = state.lookup, crosses = state.crosses;
  try {
    const response = await fetch('/api/v1/lookup/export.xlsx', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({oe_number:lookup.oe, group:lookup.group, group_raw:lookup.groupTitle, crosses})});
    if (!response.ok) throw new Error('Не удалось сформировать Excel. Повторите попытку.');
    const url = URL.createObjectURL(await response.blob()); const link = el('a');
    link.href = url; link.download = `crosses-${canonicalNumber(lookup.oe)}.xlsx`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { notice('#lookup-status', error.message, true); }
  finally { button.disabled = false; button.textContent = 'Скачать Excel'; }
};
function selectFile(file) {
  state.file = file;
  $('#file-title').textContent = file ? file.name : 'Поиск по списку номеров — загрузите Excel';
  $('#file-info').textContent = file ? `${(file.size / 1024 / 1024).toFixed(2)} МБ · нажмите, чтобы заменить` : 'Выберите или перетащите файл · XLSX · до 20 МБ';
  $('#btn-upload').textContent = file ? 'Обработать файл' : 'Выбрать файл'; notice('#job-out');
}
$('#file').onchange = () => selectFile($('#file').files[0]);
$('#dropzone').ondragover = event => { event.preventDefault(); $('#dropzone').classList.add('dragging'); };
$('#dropzone').ondragleave = () => $('#dropzone').classList.remove('dragging');
$('#dropzone').ondrop = event => { event.preventDefault(); $('#dropzone').classList.remove('dragging'); if (!state.uploading) selectFile(event.dataTransfer.files[0]); };
$('#upload-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.uploading) return;
  const file = state.file;
  if (!file) { $('#file').click(); return; }
  if (!file.name.toLowerCase().endsWith('.xlsx') || file.size > 20*1024*1024) { notice('#job-out','Нужен файл XLSX размером до 20 МБ.',true); return; }
  state.uploading = true; $('#btn-upload').disabled = true; $('#file').disabled = true;
  $('#btn-upload').textContent = 'Отправляем…'; notice('#job-out','Загружаем файл. Не закрывайте страницу.');
  const body = new FormData(); body.append('file',file);
  try {
    const job = await api('/api/v1/jobs/upload',{method:'POST',body});
    selectFile(null); $('#file').value = '';
    notice('#job-out',`Задание создано: ${file.name}. Позиций: ${job.total}.`);
    await showJob(job.id); await refreshJobs(); loadQuota();
  } catch (error) { notice('#job-out',`${error.message} Перед повторной отправкой проверьте историю заданий.`,true); }
  finally { state.uploading = false; $('#btn-upload').disabled = false; $('#file').disabled = false; $('#btn-upload').textContent = state.file ? 'Обработать файл' : 'Выбрать файл'; }
});
function jobRow(job) {
  const row = el('article',undefined,'job-row'); row.dataset.job = job.id;
  const name = el('div',job.filename || 'Задание из API','job-name');
  name.append(el('time',new Date(job.created_at).toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'}),'job-date'));
  const status = el('span',STATUS[job.status] || 'Неизвестный статус',`badge ${job.status === 'failed'?'warning':job.status === 'done'?'job-done':'neutral'}`);
  const actions = el('div',undefined,'job-actions');
  if (job.status === 'done') { const link = el('a','Скачать Excel','text-link'); link.href = `/api/v1/jobs/${encodeURIComponent(job.id)}/export.xlsx`; actions.append(link); }
  const details = el('button','Подробнее','text-button'); details.type = 'button'; details.dataset.focusKey = job.id; details.onclick = () => showJob(job.id); actions.append(details);
  row.append(name,status);
  if (['pending','running'].includes(job.status)) {
    const progress = el('div',`Обработано ${job.done} из ${job.total}`,'job-progress'); const bar = el('progress'); bar.max = Math.max(1,job.total); bar.value = job.done; bar.setAttribute('aria-label',`Обработка ${job.filename || 'задания'}`); progress.append(bar); row.append(progress);
  }
  row.append(actions); return row;
}
async function showJob(id, background = false) {
  if (background && (state.mode !== 'job' || state.selectedJob !== id)) return;
  const request = ++state.viewRequest;
  state.mode = 'job'; state.selectedJob = id; highlightJob();
  if (!background) { clearResult(); $('#results-title').textContent = 'Результат обработки'; $('#result-summary').textContent = 'Загружаем результат…'; }
  try {
    const [data, results] = await Promise.all([api(`/api/v1/jobs/${encodeURIComponent(id)}`),api(`/api/v1/jobs/${encodeURIComponent(id)}/results`)]);
    if (request !== state.viewRequest) return;
    state.jobVersion = JSON.stringify(data.job);
    state.crosses = results.rows; state.lookup = null;
    $('#results-title').textContent = 'Результат обработки'; $('#result-query').textContent = data.job.filename || 'Задание из API';
    $('#result-summary').textContent = data.job.status === 'done' ? '' : `${STATUS[data.job.status] || data.job.status} · обработано ${data.job.done} из ${data.job.total}.`;
    const problematic = data.items.filter(i => ['blocked','error','no_sources'].includes(i.status)).length;
    if (problematic) $('#result-summary').textContent += ` Для ${problematic} позиций проверка неполная — смотрите статус позиций.`;
    $('#job-export').href = `/api/v1/jobs/${encodeURIComponent(id)}/export.xlsx`; $('#job-export').hidden = data.job.status !== 'done';
    $('#btn-export-lookup').hidden = true; $('#source-details').hidden = true; $('#result-empty').hidden = true;
    renderRows();
    const table = el('table'), thead = el('thead'), head = el('tr'), tbody = el('tbody');
    for (const title of ['OE / OEM','Деталь','Статус','Кроссов']) { const th = el('th',title); th.scope = 'col'; head.append(th); }
    thead.append(head);
    for (const item of data.items) { const row = el('tr'); row.append(el('td',item.oe_number),el('td',item.part_name || item.our_sku || '—'),el('td',STATUS[item.status] || item.status),el('td',String(item.crosses_count))); tbody.append(row); }
    table.append(thead,tbody); $('#detail-body').replaceChildren(table); $('#job-details').hidden = !problematic && data.job.status === 'done';
    if (!background) $('#job-details').open = Boolean(problematic || data.job.status === 'failed');
  } catch (error) { if (request === state.viewRequest) { $('#result-summary').textContent = `${error.message} Нажмите «Подробнее» в истории, чтобы повторить.`; state.jobVersion = ''; } }
}
async function refreshJobs() {
  if (state.jobsBusy) return;
  state.jobsBusy = true; $('#refresh-jobs').disabled = true;
  try {
    const jobs = await api(`/api/v1/jobs?limit=${state.limit}`);
    state.active = jobs.some(j => ['pending','running'].includes(j.status));
    const serialized = JSON.stringify(jobs);
    if (serialized !== state.jobsJSON) {
      const focused = document.activeElement, key = focused?.dataset.focusKey;
      const href = focused?.closest('#jobs') ? focused.getAttribute('href') : null;
      $('#jobs').replaceChildren(...jobs.map(jobRow));
      if (!jobs.length) { const empty = el('div',undefined,'empty-state'); empty.append(el('strong','Здесь будут ваши файлы'),el('span','Загрузите первый Excel, чтобы начать.')); $('#jobs').append(empty); }
      highlightJob();
      if (key) [...$('#jobs').querySelectorAll('button')].find(b => b.dataset.focusKey === key)?.focus({preventScroll:true});
      if (href) [...$('#jobs').querySelectorAll('a')].find(a => a.getAttribute('href') === href)?.focus({preventScroll:true});
      state.jobsJSON = serialized;
    }
    $('#more-jobs').hidden = jobs.length < state.limit; $('#more-jobs').setAttribute('aria-expanded', String(state.limit > 2)); $('#collapse-jobs').hidden = state.limit <= 2; $('#history-status').textContent = '';
    if (state.mode === 'empty' && jobs.length) await showJob(jobs[0].id);
    else if (state.mode === 'job') {
      const selected = jobs.find(j => j.id === state.selectedJob);
      if (selected && JSON.stringify(selected) !== state.jobVersion) await showJob(selected.id,true);
    }
  } catch (error) { $('#history-status').textContent = `${error.message} История может быть неактуальна. Нажмите «Обновить».`; }
  finally { state.jobsBusy = false; $('#refresh-jobs').disabled = false; }
}
$('#refresh-jobs').onclick = refreshJobs;
$('#more-jobs').onclick = () => { if (!state.jobsBusy) { state.limit += 5; refreshJobs(); } };
$('#collapse-jobs').onclick = () => { if (!state.jobsBusy) { state.limit = 2; refreshJobs(); $('#history-title').scrollIntoView({block:'nearest'}); } };
async function poll() { if (!document.hidden) await refreshJobs(); setTimeout(poll,state.active?5000:30000); }
document.addEventListener('visibilitychange',() => { if (!document.hidden) refreshJobs(); });
loadGroups(); loadQuota(); poll();
