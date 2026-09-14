const $ = (selector) => document.querySelector(selector);
const KIND = {oem: 'OEM', aftermarket: 'Аналог', standard: 'Стандарт'};
const EXPORT_KIND = {oem: 'ОЕМ', aftermarket: 'АФТЕРМАРКЕТ', standard: 'СТАНДАРТ'};
const STATUS = {ok: 'Найдено', not_found: 'Нет совпадений', blocked: 'Недоступен', error: 'Ошибка', no_sources: 'Нет каталогов', pending: 'В очереди', running: 'Обрабатывается', done: 'Завершено', failed: 'Ошибка задания'};
const state = {crosses: [], sources: new Map(), busy: false, uploading: false, jobsBusy: false, limit: 20, active: false, jobsJSON: '', file: null};

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

async function loadGroups() {
  try {
    const [coverage, sources] = await Promise.all([api('/api/v1/groups'), api('/api/v1/sources')]);
    state.sources = new Map(sources.sources.map(source => [source.key, source]));
    const selected = $('#group').value;
    $('#group').replaceChildren(new Option('Все группы', ''));
    $('#coverage').replaceChildren();
    for (const group of coverage.groups) {
      $('#group').append(new Option(group.title, group.group));
      const row = el('div', undefined, 'coverage-row');
      row.append(el('strong', group.title));
      const enabled = sources.sources.filter(s => sources.default.includes(s.key) && (!s.groups.length || s.groups.includes(group.group)));
      row.append(...enabled.map(s => el('span', s.title, 'badge')));
      if (!enabled.length) row.append(el('span', 'Нет подключённых источников', 'badge neutral'));
      $('#coverage').append(row);
    }
    $('#group').value = selected;
    $('#retry-groups').hidden = true;
  } catch (error) {
    $('#coverage').textContent = error.message;
    $('#retry-groups').hidden = false;
  }
}
$('#retry-groups').onclick = loadGroups;

async function loadQuota() {
  try {
    const quota = await api('/api/v1/account');
    $('#quota').replaceChildren(el('span', 'Поисков осталось'), el('strong', `${quota.remaining} из ${quota.limit}`));
  } catch (_) { $('#quota').hidden = true; }
}

$('#lookup-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const oe = $('#oe').value.trim();
  if (oe.length < 2) { notice('#lookup-status', 'Введите хотя бы два символа номера.', true); $('#oe').focus(); return; }
  state.busy = true;
  $('#btn-lookup').disabled = true;
  $('#btn-lookup').textContent = 'Ищем…';
  $('#lookup-form').setAttribute('aria-busy', 'true');
  $('#results').hidden = true;
  notice('#lookup-status', 'Проверяем каталоги. Ответ может занять около минуты.');
  const groupTitle = $('#group').selectedOptions[0].textContent;
  try {
    const data = await api('/api/v1/lookup', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({oe, group: $('#group').value || null})});
    renderLookup(data, groupTitle);
    loadQuota();
    notice('#lookup-status');
  } catch (error) { notice('#lookup-status', error.message, true); }
  finally { state.busy = false; $('#btn-lookup').disabled = false; $('#btn-lookup').textContent = 'Найти кроссы →'; $('#lookup-form').removeAttribute('aria-busy'); }
});

function renderLookup(data, groupTitle) {
  state.crosses = data.crosses;
  state.lookup = {oe: data.oe, groupTitle};
  const unavailable = data.sources.filter(s => ['error', 'blocked'].includes(s.status));
  const answered = data.sources.filter(s => ['ok', 'not_found'].includes(s.status));
  let summary;
  if (data.status === 'no_sources' || !data.sources.length) summary = 'Для этой группы нет подключённых каталогов. Выберите другую группу.';
  else if (!answered.length) summary = 'Каталоги не ответили. Наличие аналогов проверить не удалось. Повторите поиск позже.';
  else if (unavailable.length) summary = `Неполный результат: ответили ${answered.length} из ${data.sources.length} каталогов. Часть источников недоступна.`;
  else if (!data.crosses.length) summary = 'В проверенных каталогах совпадений нет. Проверьте номер и товарную группу.';
  else summary = `Проверено каталогов: ${answered.length}. Совпадения объединены с сохранением источников.`;
  $('#results').hidden = false;
  $('#result-query').textContent = `${data.oe} / ${groupTitle}`;
  $('#result-count').textContent = `Номеров: ${data.unique_numbers.length} · записей: ${data.crosses.length}`;
  $('#result-summary').textContent = summary;
  $('#source-reports').replaceChildren(...data.sources.map(source => {
    const badge = el('span', `${sourceTitle(source.source)}: ${STATUS[source.status] || 'Неизвестный статус'}`, `badge ${['error', 'blocked'].includes(source.status) ? 'warning' : 'neutral'}`);
    if (source.message) badge.title = source.message;
    return badge;
  }));
  $('#result-filter').value = ''; $('#kind-filter').value = '';
  $('#result-tools').hidden = !data.crosses.length;
  renderRows();
}
function renderRows() {
  const query = $('#result-filter').value.trim().toLocaleLowerCase();
  const kind = $('#kind-filter').value;
  const rows = state.crosses.filter(c => (!kind || c.kind === kind) && `${c.brand} ${c.number}`.toLocaleLowerCase().includes(query));
  $('#filter-count').textContent = state.crosses.length ? `Показано ${rows.length} из ${state.crosses.length} кросс-номеров` : '';
  $('#result-rows').replaceChildren(...rows.map(cross => {
    const row = el('tr');
    const number = el('td'); number.append(el('code', canonicalNumber(cross.number)));
    row.append(
      el('td', state.lookup?.oe || '—'),
      el('td', cross.brand),
      number,
      el('td', EXPORT_KIND[cross.kind] || '—'),
      el('td', (cross.sources || []).map(sourceTitle).join(', ') || '—'),
    );
    return row;
  }));
  if (!rows.length) {
    const row = el('tr'); const cell = el('td', state.crosses.length ? 'По этому фильтру нет записей.' : 'Нет номеров для отображения. Статус проверки указан выше.'); cell.colSpan = 5; row.append(cell); $('#result-rows').append(row);
  }
  renderVariant2(rows);
}

function renderVariant2(crosses) {
  const groups = new Map();
  for (const cross of crosses) {
    const kind = cross.kind || 'standard';
    if (!groups.has(kind)) groups.set(kind, []);
    const numbers = groups.get(kind);
    const key = canonicalNumber(cross.number);
    if (!numbers.some(entry => entry.key === key)) numbers.push({key, number: key});
  }
  const rows = [];
  for (const kind of ['oem', 'aftermarket', 'standard']) {
    const numbers = groups.get(kind);
    if (!numbers?.length) continue;
    const row = el('tr');
    row.append(
      el('td', '—'),
      el('td', state.lookup?.groupTitle || 'Все группы'),
      el('td', state.lookup?.oe || '—'),
      el('td', String(numbers.length)),
      el('td', EXPORT_KIND[kind]),
      el('td', numbers.map(entry => entry.number).join(', ')),
    );
    rows.push(row);
  }
  $('#variant2-rows').replaceChildren(...rows);
  if (!rows.length) {
    const row = el('tr'); const cell = el('td', 'Нет номеров для формирования варианта 2.'); cell.colSpan = 6; row.append(cell); $('#variant2-rows').append(row);
  }
}
$('#result-filter').oninput = renderRows; $('#kind-filter').onchange = renderRows;

$('#btn-export-lookup').onclick = async () => {
  if (!state.lookup || !state.crosses.length) return;
  const button = $('#btn-export-lookup');
  button.disabled = true;
  button.textContent = 'Готовим Excel…';
  try {
    const response = await fetch('/api/v1/lookup/export.xlsx', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({oe_number: state.lookup.oe, group: $('#group').value || null,
                            group_raw: state.lookup.groupTitle, crosses: state.crosses}),
    });
    if (!response.ok) throw new Error('Не удалось сформировать Excel. Повторите попытку.');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = `crosses-${canonicalNumber(state.lookup.oe)}.xlsx`;
    document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  } catch (error) { notice('#lookup-status', error.message, true); }
  finally { button.disabled = false; button.textContent = 'Скачать Excel ↙'; }
};

function selectFile(file) {
  state.file = file;
  $('#file-title').textContent = file ? file.name : 'Выберите или перетащите файл';
  $('#file-info').textContent = file ? `${(file.size / 1024 / 1024).toFixed(2)} МБ · нажмите, чтобы заменить` : 'XLSX · до 20 МБ';
  notice('#job-out');
}
$('#file').onchange = () => selectFile($('#file').files[0]);
$('#dropzone').ondragover = event => { event.preventDefault(); $('#dropzone').classList.add('dragging'); };
$('#dropzone').ondragleave = () => $('#dropzone').classList.remove('dragging');
$('#dropzone').ondrop = event => { event.preventDefault(); $('#dropzone').classList.remove('dragging'); if (!state.uploading) selectFile(event.dataTransfer.files[0]); };
$('#upload-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.uploading) return;
  const file = state.file;
  if (!file) { notice('#job-out', 'Выберите Excel-файл для обработки.', true); $('#file').focus(); return; }
  if (!file.name.toLowerCase().endsWith('.xlsx') || file.size > 20 * 1024 * 1024) { notice('#job-out', 'Нужен файл XLSX размером до 20 МБ.', true); return; }
  state.uploading = true; $('#btn-upload').disabled = true; $('#file').disabled = true;
  $('#btn-upload').textContent = 'Отправляем…'; notice('#job-out', 'Загружаем файл. Не закрывайте страницу.');
  const body = new FormData(); body.append('file', file);
  try {
    const job = await api('/api/v1/jobs/upload', {method: 'POST', body});
    notice('#job-out', `Задание создано: ${file.name}. Позиций: ${job.total}. Статус и результат — в истории ниже.`);
    state.file = null; $('#file').value = ''; $('#file-title').textContent = 'Выберите следующий файл'; $('#file-info').textContent = 'XLSX · до 20 МБ';
    await refreshJobs();
    loadQuota();
  } catch (error) { notice('#job-out', `${error.message} Перед повторной отправкой проверьте историю заданий.`, true); }
  finally { state.uploading = false; $('#btn-upload').disabled = false; $('#file').disabled = false; $('#btn-upload').textContent = 'Обработать файл →'; }
});

function jobRow(job) {
  const row = el('article', undefined, 'job-row'); row.dataset.job = job.id;
  const name = el('div', job.filename || 'Задание из API', 'job-name');
  name.append(el('time', new Date(job.created_at).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'}), 'job-date'));
  const status = el('span', STATUS[job.status] || 'Неизвестный статус', `badge ${job.status === 'failed' ? 'warning' : 'neutral'}`);
  const progress = el('div', `Обработано ${job.done} из ${job.total}`, 'job-progress');
  const bar = el('progress'); bar.max = Math.max(1, job.total); bar.value = job.done; bar.setAttribute('aria-label', `Обработка ${job.filename || 'задания'}`); progress.append(bar);
  const actions = el('div', undefined, 'job-actions');
  if (job.status === 'done') { const link = el('a', 'Скачать Excel ↙', 'text-link'); link.href = `/api/v1/jobs/${encodeURIComponent(job.id)}/export.xlsx`; actions.append(link); }
  const details = el('button', 'Подробнее', 'text-button'); details.dataset.focusKey = job.id; details.onclick = () => showDetails(job.id); actions.append(details);
  row.append(name, status, progress, actions); return row;
}
async function refreshJobs() {
  if (state.jobsBusy) return;
  state.jobsBusy = true; $('#refresh-jobs').disabled = true;
  try {
    const jobs = await api(`/api/v1/jobs?limit=${state.limit}`);
    state.active = jobs.some(j => ['pending', 'running'].includes(j.status));
    const serialized = JSON.stringify(jobs);
    if (serialized !== state.jobsJSON) {
      const focused = document.activeElement;
      const key = focused?.dataset.focusKey;
      const href = focused?.closest('#jobs') ? focused.getAttribute('href') : null;
      $('#jobs').replaceChildren(...jobs.map(jobRow));
      if (!jobs.length) { const empty = el('div', undefined, 'empty-state'); empty.append(el('strong', 'Здесь будут ваши файлы'), el('span', 'Загрузите первую таблицу — сохраним ход обработки и результат.')); $('#jobs').append(empty); }
      if (key) [...$('#jobs').querySelectorAll('button')].find(b => b.dataset.focusKey === key)?.focus({preventScroll: true});
      if (href) [...$('#jobs').querySelectorAll('a')].find(a => a.getAttribute('href') === href)?.focus({preventScroll: true});
      state.jobsJSON = serialized;
    }
    $('#more-jobs').hidden = jobs.length < state.limit;
    $('#history-status').textContent = '';
  } catch (error) { $('#history-status').textContent = `${error.message} История может быть неактуальна. Нажмите «Обновить».`; }
  finally { state.jobsBusy = false; $('#refresh-jobs').disabled = false; }
}
let detailRequest = 0;
async function showDetails(id) {
  const request = ++detailRequest;
  $('#job-details').hidden = false; $('#detail-body').textContent = 'Загружаем позиции…';
  try {
    const data = await api(`/api/v1/jobs/${encodeURIComponent(id)}`);
    if (request !== detailRequest) return;
    $('#detail-title').textContent = data.job.filename || 'Состав задания';
    const totals = {};
    for (const item of data.items) totals[item.status] = (totals[item.status] || 0) + 1;
    const summary = el('p', Object.entries(totals).map(([status, count]) => `${STATUS[status] || status}: ${count}`).join(' · '));
    const table = el('table'); const head = el('tr');
    for (const title of ['OE', 'Деталь', 'Статус', 'Кроссов']) { const th = el('th', title); th.scope = 'col'; head.append(th); }
    const thead = el('thead'); thead.append(head); const tbody = el('tbody');
    for (const item of data.items) { const row = el('tr'); row.append(el('td', item.oe_number), el('td', item.part_name || item.our_sku || '—'), el('td', STATUS[item.status] || item.status), el('td', item.crosses_count)); tbody.append(row); }
    table.append(thead, tbody); $('#detail-body').replaceChildren(summary, table);
  } catch (error) { if (request === detailRequest) $('#detail-body').textContent = error.message; }
}
$('#close-details').onclick = () => { detailRequest++; $('#job-details').hidden = true; };
$('#refresh-jobs').onclick = refreshJobs;
$('#more-jobs').onclick = () => { state.limit += 20; refreshJobs(); };
async function poll() { if (!document.hidden) await refreshJobs(); setTimeout(poll, state.active ? 5000 : 30000); }
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshJobs(); });
loadGroups(); loadQuota(); poll();
