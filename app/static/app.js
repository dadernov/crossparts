const $ = (selector) => document.querySelector(selector);
const KIND = {oem: 'OEM', aftermarket: 'Аналог', standard: 'Стандарт'};
const STATUS = {ok: 'Найдено', partial: 'Найдено частично', not_found: 'Нет совпадений', blocked: 'Недоступен', error: 'Ошибка', no_sources: 'Нет каталогов', pending: 'В очереди', running: 'Обрабатывается', done: 'Завершено', failed: 'Ошибка задания'};
const state = {crosses: [], sources: new Map(), busy: false, uploading: false, jobsBusy: false, limit: 2, active: false, jobsJSON: '', file: null, mode: 'empty', selectedJob: null, jobVersion: '', viewRequest: 0, page: 1, excludedBrands: new Set(), excludedSources: new Set()};

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
    if ([400, 403, 429].includes(response.status)) { try { detail = (await response.json()).detail; } catch (_) { /* generic fallback */ } }
    throw new Error((typeof detail === 'string' ? detail : null) || messages[response.status] || 'Сервис временно недоступен. Повторите позже.');
  }
  return response.json();
}
function sourceTitle(key) { return state.sources.get(key)?.title || key; }
function canonicalNumber(value) { return String(value || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase(); }

// Accessible account disclosure; logout stays a native POST form.
const profileToggle = $('#profile-toggle');
const profileDropdown = $('#profile-dropdown');
const account = document.querySelector('.account');
const trialRequired = document.body.dataset.guest === 'true' && document.body.dataset.trialActive !== 'true';
const fitmentEnabled = document.body.dataset.fitmentEnabled === 'true';
let fitmentRequest = 0;
let fitmentPayload = null;
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
const guestOptions = $('#guest-options');
const guestLogin = $('#guest-login');
function openAccessMenu() {
  if (!profileDropdown || !profileToggle) return;
  if (guestOptions && guestLogin) { guestLogin.hidden = true; guestOptions.hidden = false; account?.classList.remove('login-open'); }
  profileDropdown.hidden = false;
  profileToggle.setAttribute('aria-expanded', 'true');
  ($('#use-trial') || $('#open-inline-login'))?.focus();
}
if (guestOptions && guestLogin) {
  $('#open-inline-login').onclick = () => {
    guestOptions.hidden = true; guestLogin.hidden = false; account?.classList.add('login-open');
    $('#header-username').focus();
  };
  $('#back-to-access').onclick = () => {
    guestLogin.hidden = true; guestOptions.hidden = false; account?.classList.remove('login-open');
    $('#open-inline-login').focus();
  };
}
const trialForm = document.querySelector('.trial-form[data-support-url]');
trialForm?.addEventListener('submit', () => {
  window.open(trialForm.dataset.supportUrl, '_blank', 'noopener,noreferrer');
});

const GROUP_EXAMPLES = {
  brake_pads: ['Колодки', '58101H5A25'], brake_discs: ['Диски', '1K0615301AA'],
  brake_hoses: ['Шланги', '1K0611701K'], shock_absorbers: ['Амортизаторы', '4851080378'],
  radiators: ['Радиаторы', '8200735038'],
};
const intentParams = new URLSearchParams(window.location.search);
const intentNumber = (intentParams.get('oe') || '').trim();
const allowedIntentGroups = new Set(Object.keys(GROUP_EXAMPLES));
let pendingIntentGroup = allowedIntentGroups.has(intentParams.get('group')) ? intentParams.get('group') : '';
const intentMode = intentParams.get('mode') === 'excel' ? 'excel' : 'single';
if (intentNumber.length >= 2 && intentNumber.length <= 128 && !/[\u0000-\u001f\u007f]/.test(intentNumber)) {
  $('#oe').value = intentNumber;
}
const SOURCE_LOGOS = {sbparts:'sbparts.svg', brembo:'brembo.svg', trialli:'trialli.svg', brixo:'brixo.svg', luzar:'luzar.svg', nissens:'nissens.svg', kyb:'kyb.png', hola:'hola.svg', brannor:'brannor.svg', hel:'hel.png', metaco:'metaco.svg', marshall:'marshall.svg', lynxauto:'lynxauto.svg', masterkit:'masterkit.svg', fap:'fap.svg', ganz:'ganz.svg', zimmermann:'zimmermann.png', monaer:'monaer.png', ate:'ate.png', febest:'febest.svg', torr:'torr.png'};
const RESULT_BRAND_LOGOS = {
  'ABS':'abs', 'AKEBONO':'akebono', 'ALFA ROMEO':'alfa-romeo', 'APEC':'apec',
  'ASTON MARTIN':'aston-martin', 'ATE':'ate', 'AUDI':'audi', 'BENDIX':'bendix', 'BENTLEY':'bentley',
  'BILSTEIN':'bilstein', 'BMW':'bmw', 'BOSCH':'bosch', 'BRANNOR':'../brands/brannor',
  'BREMBO':'../brands/brembo', 'BRIXO':'../brands/brixo', 'BORG AND BECK':'borg-beck',
  'CHEVROLET':'chevrolet', 'CHERY':'chery', 'CHRYSLER':'chrysler', 'CITROEN':'citroen',
  'CUPRA':'cupra', 'DACIA':'dacia', 'DELPHI':'delphi', 'DENSO':'denso', 'DODGE':'dodge',
  'EBC BRAKES':'ebc-brakes',
  'FEBI':'febi-bilstein', 'FEBI BILSTEIN':'febi-bilstein', 'FERODO':'ferodo',
  'FIAT':'fiat', 'FORD':'ford', 'GEELY':'geely', 'GENERAL MOTORS':'general-motors',
  'HELLA':'hella', 'HELLA PAGID':'hella', 'HITACHI':'hitachi',
  'HEL':'../brands/hel', 'HOLA':'../brands/hola', 'HONDA':'honda', 'HYUNDAI':'hyundai',
  'JAGUAR':'jaguar', 'JEEP':'jeep', 'KIA':'kia', 'KYB':'../brands/kyb', 'LADA':'lada',
  'LEXUS':'lexus', 'LINCOLN':'lincoln', 'LPR':'lpr', 'LUZAR':'../brands/luzar',
  'MAHLE':'mahle', 'MASERATI':'maserati', 'MAZDA':'mazda',
  'MERCEDES BENZ':'mercedes', 'MITSUBISHI':'mitsubishi',
  'MEYLE':'meyle', 'NGK':'ngk', 'NIBK':'nibk', 'NISSAN':'nissan', 'NISSENS':'../brands/nissens',
  'NISSHINBO':'nisshinbo', 'NK':'nk', 'OPEL':'opel', 'PAGID':'pagid', 'PEUGEOT':'peugeot',
  'PORSCHE':'porsche', 'QUINTON HAZELL':'quinton-hazell', 'REMSA':'remsa',
  'RAM':'ram', 'RENAULT':'renault', 'ROADHOUSE':'roadhouse', 'ROLLS ROYCE':'rolls-royce',
  'SAAB':'saab', 'SAKURA':'sakura', 'SB NAGAMOCHI':'../brands/sbparts', 'SBS':'sbs',
  'SEAT':'seat', 'SKF':'skf', 'SKODA':'skoda', 'SUBARU':'subaru', 'SUZUKI':'suzuki',
  'TESLA':'tesla', 'TEXTAR':'textar', 'JURID':'jurid', 'TOYOTA':'toyota',
  'TRIALLI':'../brands/trialli', 'TRW':'trw', 'VALEO':'valeo',
  'VAUXHALL':'vauxhall', 'VOLKSWAGEN':'volkswagen', 'VOLVO':'volvo',
  'ZIMMERMANN':'zimmermann', 'BECK ARNLEY':'beck-arnley', 'BYD':'byd',
};
const BRAND_ALIASES = {
  'A B S':'ABS', 'DAIMLER':'MERCEDES BENZ', 'DAIMLER AG':'MERCEDES BENZ',
  'GM':'GENERAL MOTORS', 'MERCEDES':'MERCEDES BENZ', 'MERCEDES BENZ FJDA':'MERCEDES BENZ',
  'FAW VW':'VOLKSWAGEN', 'ROBERT BOSCH':'BOSCH', 'SAIC VOLKSWAGEN':'VOLKSWAGEN',
  'VAG':'VOLKSWAGEN', 'VAG JZW':'VOLKSWAGEN', 'VW':'VOLKSWAGEN',
};
const BRAND_SUFFIXES = [' ASIA',' BEIJING',' BRILLIANCE',' CHANGAN',' DONGFENG',' FAW',' GAC',' HAINAN',' SVW',' USA'];
const NON_BRANDS = new Set(['OEM','OTHER','TEST']);
function normalizedBrand(value) {
  let key = String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .toUpperCase().replace(/&/g, ' AND ').replace(/[^A-Z0-9]+/g, ' ').trim();
  for (const suffix of BRAND_SUFFIXES) if (key.endsWith(suffix)) key = key.slice(0, -suffix.length);
  return BRAND_ALIASES[key] || key;
}
function brandLogo(value) {
  const slug = RESULT_BRAND_LOGOS[normalizedBrand(value)];
  if (!slug) return null;
  const extension = ['ate','nibk','sakura','../brands/kyb','../brands/hel'].includes(slug) ? 'png' : 'svg';
  return `/static/images/result-brands/${slug}.${extension}`.replace('/result-brands/../brands/', '/brands/');
}
function brandCell(value) {
  const cell = el('td'); const wrap = el('span', undefined, 'result-brand');
  const normalized = normalizedBrand(value);
  if (NON_BRANDS.has(normalized)) { wrap.append(el('span', '—')); cell.append(wrap); return cell; }
  wrap.append(el('span', value || '—')); cell.append(wrap); return cell;
}
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
    const selected = $('#group').value || pendingIntentGroup;
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
    pendingIntentGroup = '';
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
  resetColumnFilters();
  $('#result-rows').replaceChildren(); $('#result-table').hidden = true; $('#result-tools').hidden = true;
  $('#result-empty').hidden = true; $('#result-filter').value = ''; $('#filter-count').textContent = '';
  $('#result-count').textContent = ''; $('#result-query').textContent = '';
  $('#btn-export-lookup').hidden = true; $('#job-export').hidden = true; $('#export-format').hidden = true;
  $('#source-details').hidden = true; $('#job-details').hidden = true;
  closeFitment();
}
function revealSearchActivity() {
  $('#results').hidden = false;
  $('.history-panel').hidden = false;
}
function highlightJob() {
  for (const row of $('#jobs').children) row.classList.toggle('selected', row.dataset.job === state.selectedJob);
}
$('#lookup-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy) return;
  const oe = $('#oe').value.trim();
  if (oe.length < 2) { notice('#lookup-status', 'Введите хотя бы два символа номера.', true); $('#oe').focus(); return; }
  if (trialRequired) { openAccessMenu(); return; }
  revealSearchActivity();
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
    state.lookup = {oe: data.oe, group, groupTitle}; state.crosses = data.crosses; resetColumnFilters();
    const answered = data.sources.filter(s => ['ok','not_found','partial'].includes(s.status));
    const unavailable = data.sources.filter(s => ['error','blocked','partial'].includes(s.status));
    let summary;
    if (data.status === 'no_sources' || !data.sources.length) summary = 'Для этой группы нет подключённых каталогов. Выберите другую группу.';
    else if (!answered.length) summary = 'Каталоги не ответили. Наличие аналогов проверить не удалось. Повторите поиск позже.';
    else if (unavailable.length) summary = `Неполный результат: ответили ${answered.length} из ${data.sources.length} каталогов. Часть источников недоступна.`;
    else if (!data.crosses.length) summary = 'В проверенных каталогах совпадений нет. Проверьте номер и товарную группу.';
    else summary = '';
    $('#result-summary').textContent = summary;
    $('#result-query').textContent = `${data.oe} · ${groupTitle}`;
    $('#source-reports').replaceChildren(...data.sources.map(source => el('span', `${sourceTitle(source.source).replace(/\s*\([^()]*\)\s*$/, '')}: ${STATUS[source.status] || source.status}`, `badge ${['error','blocked','partial'].includes(source.status)?'warning':'neutral'}`)));
    $('#source-summary').textContent = `Каталоги: ${answered.length} из ${data.sources.length}`;
    $('#source-details').hidden = !unavailable.length;
    // Keep the compact catalogue summary closed after search. The user can
    // expand diagnostics when needed; errors must not open a large overlay.
    $('#source-details').open = false;
    $('#btn-export-lookup').hidden = !data.crosses.length; $('#export-format').hidden = !data.crosses.length;
    renderRows(); loadQuota(); refreshJobs(); notice('#lookup-status');
  } catch (error) { if (request === state.viewRequest) { notice('#lookup-status', error.message, true); $('#result-summary').textContent = error.message; } }
  finally { state.busy = false; $('#btn-lookup').disabled = false; $('#btn-lookup').textContent = 'Найти'; $('#lookup-form').removeAttribute('aria-busy'); }
});
function renderRows() {
  const query = $('#result-filter').value.trim().toLocaleLowerCase();
  const canonicalQuery = canonicalNumber(query);
  const rows = state.crosses.filter(c => {
    if (state.excludedBrands.has(c.brand || '—')) return false;
    const rowSources = c.sources || [];
    if (rowSources.length && rowSources.every(source => state.excludedSources.has(source))) return false;
    if (!query) return true;
    const oe = c.oe_number || state.lookup?.oe || '';
    const sources = (c.sources || []).map(sourceTitle).join(' ');
    const text = `${oe} ${c.brand} ${c.number} ${sources}`.toLocaleLowerCase();
    return text.includes(query) || (canonicalQuery && [oe, c.number].some(value => canonicalNumber(value).includes(canonicalQuery)));
  });
  $('#result-count').textContent = state.crosses.length ? `${state.crosses.length} номеров` : '';
  $('#result-tools').hidden = !state.crosses.length; $('#result-table').hidden = false;
  if ($('#fitment-batch')) {
    $('#fitment-batch').hidden = !state.crosses.some(cross => fitmentGroupFor(cross));
  }
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
    row.append(el('td', String(start + index + 1)), el('td', cross.oe_number || state.lookup?.oe || '—'), brandCell(cross.brand), number, el('td', (cross.sources || []).map(key => sourceTitle(key).replace(/\s*\([^()]*\)\s*$/, '')).join(', ') || '—'));
    if (fitmentEnabled) {
      const action = el('td');
      const group = fitmentGroupFor(cross);
      if (state.mode === 'lookup' && group) {
        const button = el('button', 'Показать', 'fitment-action'); button.type = 'button';
        button.setAttribute('aria-label', `Показать применяемость ${String(cross.brand || '').toUpperCase()} ${canonicalNumber(cross.number)}`);
        button.onclick = () => loadFitment(cross, button, group);
        action.append(button);
      } else action.textContent = '—';
      row.append(action);
    }
    return row;
  }));
  if (!rows.length) { const row = el('tr'); const cell = el('td', state.crosses.length ? 'По этому фильтру нет записей.' : 'Нет номеров для отображения. Статус проверки указан выше.'); cell.colSpan = fitmentEnabled ? 6 : 5; row.append(cell); $('#result-rows').append(row); }
}
$('#result-filter').oninput = () => { state.page = 1; renderRows(); };

function closeFitment(restoreFocus = false) {
  const panel = $('#fitment-panel');
  if (!panel) return;
  fitmentRequest += 1;
  const trigger = panel._trigger;
  panel.hidden = true; panel._trigger = null;
  $('#fitment-product').replaceChildren(); $('#fitment-table').replaceChildren();
  $('#fitment-status').textContent = '';
  fitmentPayload = null;
  if ($('#fitment-export')) $('#fitment-export').hidden = true;
  if ($('#fitment-job-export')) { $('#fitment-job-export').hidden = true; $('#fitment-job-export').removeAttribute('href'); }
  if (restoreFocus && trigger?.isConnected) trigger.focus();
}
$('#fitment-close')?.addEventListener('click', () => closeFitment(true));

function fitmentGroupFor(cross) {
  const brand = String(cross.brand || '').trim().toUpperCase();
  if (!['TRIALLI', 'TORR', 'KYB', 'HOLA', 'METACO'].includes(brand)) return null;
  if (state.lookup?.group === 'shock_absorbers') return 'shock_absorbers';
  try {
    const url = new URL(cross.url);
    if (brand === 'TRIALLI' && url.hostname === 'trialli.ru' && url.pathname.startsWith('/catalogue/amortizatory-i-opory/amortizatory/')) return 'shock_absorbers';
    if (brand === 'TORR' && url.hostname === 'controltorr.de' && url.pathname.includes('/catalog/')) return 'shock_absorbers';
    if (brand === 'KYB' && url.hostname === 'kyb.ru') return 'shock_absorbers';
    if (brand === 'HOLA' && url.hostname === 'www.hola-auto.ru' && url.pathname.startsWith('/production/shock-absorbers/')) return 'shock_absorbers';
    if (brand === 'METACO' && url.hostname === 'metaco.parts' && url.pathname.includes('/catalog/')) return 'shock_absorbers';
  } catch (_) { /* a result without an official product URL is not eligible */ }
  return null;
}

async function loadFitment(cross, button, group) {
  const panel = $('#fitment-panel');
  if (!panel || !fitmentEnabled) return;
  const request = ++fitmentRequest;
  const brand = String(cross.brand || '').trim().toUpperCase();
  const payload = {brand, number:cross.number, group};
  panel._trigger = button; panel.hidden = false;
  $('#fitment-title').textContent = `Применимость ${canonicalNumber(cross.number)}`;
  $('#fitment-label').textContent = `${brand} · АМОРТИЗАТОРЫ`;
  $('#fitment-status').textContent = `Получаем данные из карточки ${brand}…`;
  $('#fitment-product').replaceChildren(); $('#fitment-table').replaceChildren();
  fitmentPayload = null; $('#fitment-export').hidden = true;
  button.disabled = true; panel.scrollIntoView({behavior:'smooth', block:'nearest'});
  try {
    const data = await api('/api/v1/fitment/lookup', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload),
    });
    if (request !== fitmentRequest) return;
    const status = $('#fitment-status');
    if (data.status !== 'ok' || !data.applications.length) {
      status.textContent = data.message || `В карточке ${brand} применяемость не указана.`;
      return;
    }
    status.textContent = `${data.applications.length} строк · ${data.cached ? 'из кеша' : 'получено сейчас'}. Данные ${brand} справочные.`;
    fitmentPayload = payload; $('#fitment-export').hidden = false;
    const product = $('#fitment-product');
    product.append(el('strong', data.title || `${data.brand} ${canonicalNumber(data.number)}`));
    const facts = [data.installation_position, data.damper_type, data.damper_kind].filter(Boolean);
    if (facts.length) product.append(el('p', facts.join(' · '), 'muted'));
    if (data.source_url) {
      const source = el('a', `Открыть карточку ${brand} ↗`, 'fitment-source');
      source.href = data.source_url; source.target = '_blank'; source.rel = 'noopener noreferrer';
      product.append(source);
    }
    const table = el('table');
    const head = el('thead'); const headRow = el('tr');
    ['Марка','Модель','Модификация','Двигатель','Мощность / объём','Годы','Ограничения'].forEach(title => { const cell = el('th', title); cell.scope = 'col'; headRow.append(cell); });
    head.append(headRow); table.append(head);
    const body = el('tbody');
    for (const item of data.applications) {
      const row = el('tr');
      const model = [item.model, item.generation && !String(item.model || '').includes(item.generation) ? item.generation : ''].filter(Boolean).join(' ');
      row.append(el('td', item.make || '—'), el('td', model || '—'), el('td', item.modification || '—'), el('td', item.engine_code || '—'), el('td', [item.power_kw && `${item.power_kw} кВт`, item.power_hp && `${item.power_hp} лс`, item.engine_cc && `${item.engine_cc} см³`].filter(Boolean).join(' · ') || '—'), el('td', item.raw_period || '—'), el('td', (item.restrictions || []).join(' · ') || item.info || '—'));
      body.append(row);
    }
    table.append(body); $('#fitment-table').append(table);
  } catch (error) {
    if (request === fitmentRequest) $('#fitment-status').textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function batchFitmentParts() {
  const parts = [], seen = new Set();
  for (const cross of state.crosses) {
    const group = fitmentGroupFor(cross);
    const brand = String(cross.brand || '').trim().toUpperCase();
    const number = canonicalNumber(cross.number);
    const key = `${brand}:${number}:${group}`;
    if (group && number && !seen.has(key)) {
      seen.add(key); parts.push({brand, number:cross.number, group});
    }
    if (parts.length === 100) break;
  }
  return parts;
}

function renderFitmentJob(data) {
  const table = el('table');
  const head = el('thead'); const headRow = el('tr');
  ['Бренд', 'Артикул', 'Статус', 'Строк применяемости', 'Сообщение'].forEach(title => {
    const cell = el('th', title); cell.scope = 'col'; headRow.append(cell);
  });
  head.append(headRow); table.append(head);
  const body = el('tbody');
  for (const result of data.results || []) {
    const row = el('tr');
    row.append(el('td', result.brand || '—'), el('td', canonicalNumber(result.number) || '—'),
      el('td', STATUS[result.status] || result.status || '—'),
      el('td', String((result.applications || []).length)), el('td', result.message || '—'));
    body.append(row);
  }
  table.append(body); $('#fitment-table').replaceChildren(table);
}

$('#fitment-batch')?.addEventListener('click', async event => {
  const button = event.currentTarget; const parts = batchFitmentParts();
  if (!parts.length) return;
  const panel = $('#fitment-panel'); const request = ++fitmentRequest;
  panel._trigger = button; panel.hidden = false; button.disabled = true;
  $('#fitment-title').textContent = 'Применимость списка';
  $('#fitment-label').textContent = 'АМОРТИЗАТОРЫ · ПАКЕТ';
  $('#fitment-product').replaceChildren(); $('#fitment-table').replaceChildren();
  $('#fitment-export').hidden = true; $('#fitment-job-export').hidden = true;
  $('#fitment-status').textContent = `Ставим в очередь ${parts.length} деталей…`;
  panel.scrollIntoView({behavior:'smooth', block:'nearest'});
  try {
    let data = await api('/api/v1/fitment/jobs', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({parts, idempotency_key:`web-${crypto.randomUUID()}`}),
    });
    while (request === fitmentRequest && ['queued', 'running'].includes(data.status)) {
      $('#fitment-status').textContent = `Обработано ${data.processed_count} из ${data.total}…`;
      await new Promise(resolve => setTimeout(resolve, 1000));
      data = await api(`/api/v1/fitment/jobs/${data.id}`);
    }
    if (request !== fitmentRequest) return;
    renderFitmentJob(data);
    const found = (data.results || []).filter(result => result.status === 'ok').length;
    $('#fitment-status').textContent = `Обработано ${data.processed_count} из ${data.total} · найдено у ${found} деталей.`;
    const download = $('#fitment-job-export');
    download.href = `/api/v1/fitment/jobs/${data.id}/export.xlsx`;
    download.download = `fitment-${data.id}.xlsx`; download.hidden = false;
  } catch (error) {
    if (request === fitmentRequest) $('#fitment-status').textContent = error.message;
  } finally { button.disabled = false; }
});

$('#fitment-export')?.addEventListener('click', async event => {
  if (!fitmentPayload) return;
  const button = event.currentTarget; button.disabled = true;
  try {
    const response = await fetch('/api/v1/fitment/export.xlsx', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(fitmentPayload),
      signal:AbortSignal.timeout(90000),
    });
    if (!response.ok) {
      let detail; try { detail = (await response.json()).detail; } catch (_) { /* fallback below */ }
      throw new Error(typeof detail === 'string' ? detail : 'Не удалось скачать применяемость.');
    }
    const url = URL.createObjectURL(await response.blob()); const link = el('a');
    link.href = url; link.download = `fitment-${fitmentPayload.brand.toLowerCase()}-${canonicalNumber(fitmentPayload.number)}.xlsx`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { $('#fitment-status').textContent = error.message; }
  finally { button.disabled = false; }
});

const columnFilters = {
  brand: {trigger: $('#brand-filter-trigger'), menu: $('#brand-filter-menu'), excluded: state.excludedBrands},
  source: {trigger: $('#source-filter-trigger'), menu: $('#source-filter-menu'), excluded: state.excludedSources},
};
function columnFilterOptions(kind) {
  if (kind === 'brand') return [...new Set(state.crosses.map(c => c.brand || '—'))]
    .sort((a, b) => a.localeCompare(b, 'ru')).map(value => ({value, label:value}));
  return [...new Set(state.crosses.flatMap(c => c.sources || []))]
    .sort((a, b) => sourceTitle(a).localeCompare(sourceTitle(b), 'ru'))
    .map(value => ({value, label:sourceTitle(value).replace(/\s*\([^()]*\)\s*$/, '')}));
}
function closeColumnFilters(restoreFocus = false) {
  for (const filter of Object.values(columnFilters)) {
    const wasOpen = !filter.menu.hidden;
    filter.menu.hidden = true; filter.trigger.setAttribute('aria-expanded', 'false');
    if (restoreFocus && wasOpen) filter.trigger.focus();
  }
}
function positionColumnFilter(filter) {
  const rect = filter.trigger.getBoundingClientRect();
  const width = filter.menu.offsetWidth;
  filter.menu.style.top = `${Math.min(innerHeight - filter.menu.offsetHeight - 12, rect.bottom + 6)}px`;
  filter.menu.style.left = `${Math.max(12, Math.min(innerWidth - width - 12, rect.left))}px`;
}
function renderColumnFilter(kind) {
  const filter = columnFilters[kind];
  const options = columnFilterOptions(kind);
  const actions = el('div', undefined, 'column-filter-actions');
  const all = el('button', 'Выбрать все'); all.type = 'button';
  const none = el('button', 'Снять все'); none.type = 'button';
  const applySelection = excluded => {
    filter.excluded.clear(); excluded.forEach(value => filter.excluded.add(value));
    state.page = 1; renderColumnFilter(kind); renderRows(); positionColumnFilter(filter);
  };
  all.onclick = () => applySelection([]);
  none.onclick = () => applySelection(options.map(option => option.value));
  actions.append(all, none);
  const list = el('div', undefined, 'column-filter-options');
  for (const option of options) {
    const label = el('label'); const input = el('input'); input.type = 'checkbox';
    input.checked = !filter.excluded.has(option.value);
    input.onchange = () => {
      input.checked ? filter.excluded.delete(option.value) : filter.excluded.add(option.value);
      state.page = 1; updateColumnFilterTrigger(kind); renderRows();
    };
    label.append(input, el('span', option.label)); list.append(label);
  }
  filter.menu.replaceChildren(actions, list);
  updateColumnFilterTrigger(kind);
}
function updateColumnFilterTrigger(kind) {
  const filter = columnFilters[kind];
  filter.trigger.classList.toggle('active', filter.excluded.size > 0);
  const title = kind === 'brand' ? 'Бренд' : 'Источник';
  filter.trigger.setAttribute('aria-label', filter.excluded.size ? `${title}: скрыто ${filter.excluded.size}` : `${title}: показать фильтр`);
}
function resetColumnFilters() {
  state.excludedBrands.clear(); state.excludedSources.clear();
  if (typeof columnFilters !== 'undefined') {
    closeColumnFilters(); renderColumnFilter('brand'); renderColumnFilter('source');
  }
}
for (const [kind, filter] of Object.entries(columnFilters)) {
  filter.trigger.onclick = event => {
    event.stopPropagation(); const open = filter.menu.hidden; closeColumnFilters();
    if (open) { renderColumnFilter(kind); filter.menu.hidden = false; filter.trigger.setAttribute('aria-expanded', 'true'); positionColumnFilter(filter); filter.menu.querySelector('input,button')?.focus(); }
  };
  filter.menu.onclick = event => event.stopPropagation();
}
document.addEventListener('click', () => closeColumnFilters());
document.addEventListener('keydown', event => { if (event.key === 'Escape' && Object.values(columnFilters).some(filter => !filter.menu.hidden)) { closeColumnFilters(true); event.preventDefault(); } });
window.addEventListener('resize', () => closeColumnFilters());
window.addEventListener('scroll', event => {
  if (!(event.target instanceof Element && event.target.closest('.column-filter-menu'))) closeColumnFilters();
}, true);
// Styled format selector with native value retained for export handlers.
function styleFormat(select) {
  const wrapper = el('div', undefined, 'format-picker');
  const trigger = el('button', select.value.toUpperCase(), 'format-trigger'); trigger.type = 'button';
  trigger.setAttribute('aria-label', select.getAttribute('aria-label') || 'Формат скачивания');
  trigger.setAttribute('aria-haspopup', 'listbox'); trigger.setAttribute('aria-expanded', 'false');
  const list = el('div', undefined, 'format-options'); list.hidden = true; list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', 'Форматы файлов');
  const close = () => { list.hidden = true; trigger.setAttribute('aria-expanded','false'); };
  const items = [];
  const sync = () => {
    trigger.textContent = select.value.toUpperCase();
    items.forEach(item => item.setAttribute('aria-selected', String(item.dataset.value === select.value)));
  };
  for (const option of select.options) {
    const item = el('button', undefined, 'format-option'); item.type = 'button'; item.dataset.value = option.value;
    item.setAttribute('role','option');
    item.append(el('strong', option.textContent));
    item.onclick = () => { select.value = option.value; select.dispatchEvent(new Event('change', {bubbles:true})); close(); trigger.focus(); };
    item.onkeydown = event => {
      const index = items.indexOf(item);
      if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
        event.preventDefault(); items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
      }
    };
    items.push(item); list.append(item);
  }
  const open = () => { list.hidden = false; trigger.setAttribute('aria-expanded','true'); items.find(item => item.dataset.value === select.value)?.focus(); };
  trigger.onclick = () => list.hidden ? open() : close();
  trigger.onkeydown = event => { if (['ArrowDown','ArrowUp'].includes(event.key)) { event.preventDefault(); open(); } };
  wrapper.onkeydown = event => { if (event.key === 'Escape') { close(); trigger.focus(); event.preventDefault(); } };
  wrapper.addEventListener('focusout', event => { if (!wrapper.contains(event.relatedTarget)) close(); });
  wrapper.append(trigger,list); select.after(wrapper); select.classList.add('format-native'); select.tabIndex = -1;
  select.addEventListener('change', sync); sync();
}
styleFormat($('#export-format'));
function downloadRows(rows, format, filename, oe = '') {
  const data = rows.map(row => ({...row, oe_number:row.oe_number || oe}));
  let content, type;
  if (format === 'json') { content = JSON.stringify(data, null, 2); type = 'application/json;charset=utf-8'; }
  else {
    const quote = value => { let text = String(value ?? ''); if (/^[\s]*[=+@-]/.test(text)) text = "'" + text; return '"' + text.replace(/"/g, '""') + '"'; };
    const records = data.map(row => [row.oe_number, row.brand, row.number, (row.sources || []).map(sourceTitle).join(', ')]);
    content = '\uFEFF' + [['Номер OE / OEM','Бренд','Номер аналога','Источник'], ...records].map(row => row.map(quote).join(';')).join('\r\n');
    type = 'text/csv;charset=utf-8';
  }
  const url = URL.createObjectURL(new Blob([content], {type}));
  const link = el('a'); link.href = url; link.download = `${filename}.${format}`; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#job-export').onclick = event => {
  const format = $('#export-format').value;
  if (format !== 'xlsx') { event.preventDefault(); downloadRows(state.crosses, format, `crosses-${state.selectedJob}`); }
};
$('#btn-export-lookup').onclick = async () => {
  if (!state.lookup || !state.crosses.length) return;
  const format = $('#export-format').value;
  if (format !== 'xlsx') { downloadRows(state.crosses, format, `crosses-${canonicalNumber(state.lookup.oe)}`, state.lookup.oe); return; }
  const button = $('#btn-export-lookup'); button.disabled = true; button.textContent = 'Готовим Excel…';
  const lookup = state.lookup, crosses = state.crosses;
  try {
    const response = await fetch('/api/v1/lookup/export.xlsx', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({oe_number:lookup.oe, group:lookup.group, group_raw:lookup.groupTitle, crosses})});
    if (!response.ok) throw new Error('Не удалось сформировать Excel. Повторите попытку.');
    const url = URL.createObjectURL(await response.blob()); const link = el('a');
    link.href = url; link.download = `crosses-${canonicalNumber(lookup.oe)}.xlsx`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { notice('#lookup-status', error.message, true); }
  finally { button.disabled = false; button.textContent = 'Скачать'; }
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
  if (trialRequired) { openAccessMenu(); return; }
  const file = state.file;
  if (!file) { $('#file').click(); return; }
  if (!file.name.toLowerCase().endsWith('.xlsx') || file.size > 20*1024*1024) { notice('#job-out','Нужен файл XLSX размером до 20 МБ.',true); return; }
  revealSearchActivity();
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
  if (job.status === 'done') {
    const format = el('select', undefined, 'export-format'); format.setAttribute('aria-label', `Формат скачивания ${job.filename || 'задания'}`);
    for (const value of ['xlsx','csv','json']) { const option = el('option', value.toUpperCase()); option.value = value; format.append(option); }
    const link = el('a','Скачать','text-link'); link.href = `/api/v1/jobs/${encodeURIComponent(job.id)}/export.xlsx`;
    link.onclick = async event => {
      if (format.value === 'xlsx') return;
      event.preventDefault(); if (link.dataset.busy) return;
      const selectedFormat = format.value; link.dataset.busy = '1'; link.textContent = 'Готовим…';
      try { const data = await api(`/api/v1/jobs/${encodeURIComponent(job.id)}/results`); downloadRows(data.rows, selectedFormat, `crosses-${job.id}`); }
      catch (error) { $('#history-status').textContent = error.message; }
      finally { delete link.dataset.busy; link.textContent = 'Скачать'; }
    };
    actions.append(format,link); styleFormat(format);
  }
  const details = el('button','Открыть','text-button'); details.type = 'button'; details.dataset.focusKey = job.id; details.onclick = () => { showJob(job.id); $('#results').scrollIntoView({block:'start', behavior:'smooth'}); }; actions.append(details);
  row.append(name,status);
  {
    const progress = el('div',`Обработано ${job.done} из ${job.total}`,'job-progress'); const bar = el('progress'); bar.max = Math.max(1,job.total); bar.value = job.done; bar.setAttribute('aria-label',`Обработка ${job.filename || 'задания'}`); progress.append(bar); row.append(progress);
  }
  row.append(actions); return row;
}
async function showJob(id, background = false) {
  revealSearchActivity();
  if (background && (state.mode !== 'job' || state.selectedJob !== id)) return;
  const request = ++state.viewRequest;
  state.mode = 'job'; state.selectedJob = id; highlightJob();
  if (!background) { clearResult(); $('#results-title').textContent = 'Результаты поиска'; $('#result-summary').textContent = 'Загружаем результат…'; }
  try {
    const [data, results] = await Promise.all([api(`/api/v1/jobs/${encodeURIComponent(id)}`),api(`/api/v1/jobs/${encodeURIComponent(id)}/results`)]);
    if (request !== state.viewRequest) return;
    state.jobVersion = JSON.stringify(data.job);
    state.crosses = results.rows; state.lookup = null; resetColumnFilters();
    $('#results-title').textContent = 'Результаты поиска'; $('#result-query').textContent = data.job.filename || 'Задание из API';
    $('#result-summary').textContent = data.job.status === 'done' ? '' : `${STATUS[data.job.status] || data.job.status} · обработано ${data.job.done} из ${data.job.total}.`;
    const problematic = data.items.filter(i => ['blocked','error','no_sources'].includes(i.status)).length;
    if (problematic) $('#result-summary').textContent += ` Для ${problematic} позиций проверка неполная — смотрите статус позиций.`;
    $('#job-export').href = `/api/v1/jobs/${encodeURIComponent(id)}/export.xlsx`; $('#job-export').hidden = data.job.status !== 'done'; $('#export-format').hidden = data.job.status !== 'done';
    $('#btn-export-lookup').hidden = true; $('#source-details').hidden = true; $('#result-empty').hidden = true;
    renderRows();
    const table = el('table'), thead = el('thead'), head = el('tr'), tbody = el('tbody');
    for (const title of ['OE / OEM','Деталь','Статус','Кроссов']) { const th = el('th',title); th.scope = 'col'; head.append(th); }
    thead.append(head);
    for (const item of data.items) { const row = el('tr'); row.append(el('td',item.oe_number),el('td',item.part_name || item.our_sku || '—'),el('td',STATUS[item.status] || item.status),el('td',String(item.crosses_count))); tbody.append(row); }
    table.append(thead,tbody); $('#detail-body').replaceChildren(table); $('#job-details').hidden = !problematic && data.job.status === 'done';
    if (!background) $('#job-details').open = Boolean(problematic || data.job.status === 'failed');
  } catch (error) { if (request === state.viewRequest) { $('#result-summary').textContent = `${error.message} Нажмите «Открыть» в истории, чтобы повторить.`; state.jobVersion = ''; } }
}
async function refreshJobs() {
  if (state.jobsBusy) return;
  state.jobsBusy = true; $('#refresh-jobs').disabled = true;
  try {
    const jobs = await api(`/api/v1/jobs?limit=${state.limit}`);
    $('.history-panel').hidden = jobs.length === 0;
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
    if (state.mode === 'job') {
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
if (intentMode === 'excel') {
  requestAnimationFrame(() => {
    $('#dropzone').scrollIntoView({block: 'center'});
    $('#btn-upload').focus({preventScroll: true});
  });
}
