const $ = (s) => document.querySelector(s);
const KIND_RU = { oem: 'OEM', aftermarket: 'Афтермаркет', standard: 'Стандарт' };
const chosenSources = () =>
  [...document.querySelectorAll('.src:checked')].map((e) => e.value);

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.text()).slice(0, 300));
  return res.json();
}

async function loadGroups() {
  try {
    const { groups } = await api('/api/v1/groups');
    $('#coverage').innerHTML = groups
      .map((g) => `<tr><td>${g.title}</td>
        <td>${g.implemented.length ? g.implemented.map((b) => `<span class="pill ok">${b}</span>`).join(' ') : '<span class="note">—</span>'}</td>
        <td>${g.blocked.length ? g.blocked.map((b) => `<span class="pill blocked">${b}</span>`).join(' ') : '<span class="note">—</span>'}</td>
        <td class="note">${g.planned.join(', ') || '—'}</td></tr>`)
      .join('');
    const sel = $('#group');
    for (const g of groups) {
      const o = document.createElement('option');
      o.value = g.group;
      o.textContent = `${g.title} (${g.implemented.length} из ${g.total})`;
      sel.appendChild(o);
    }
  } catch (_) {}
}
loadGroups();

$('#btn-lookup').onclick = async () => {
  const oe = $('#oe').value.trim();
  if (!oe) return;
  const out = $('#lookup-out');
  out.innerHTML = '<p class="hint">Ищем…</p>';
  try {
    const data = await api('/api/v1/lookup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        oe,
        sources: chosenSources(),
        fresh: $('#fresh').checked,
        group: $('#group').value || null,
      }),
    });
    out.innerHTML = renderLookup(data);
  } catch (e) {
    out.innerHTML = `<p class="warn">Ошибка: ${e.message}</p>`;
  }
};

function renderLookup(d) {
  const src = d.sources
    .map((s) => `<span class="pill ${s.status}">${s.source}: ${s.status}${
      s.crosses ? ' · ' + s.crosses : ''}${s.message ? ' · ' + s.message : ''}</span>`)
    .join(' ');
  const rows = d.crosses
    .map((c) => `<tr><td>${c.brand}</td><td><code>${c.number}</code></td>
      <td>${KIND_RU[c.kind] || c.kind}</td><td class="note">${c.sources.join(', ')}</td></tr>`)
    .join('');
  return `<p>${src}</p>
    <p class="hint">Уникальных номеров: <b>${d.unique_numbers.length}</b>, строк бренд+номер: <b>${d.crosses.length}</b></p>
    <div class="scroll"><table><thead><tr><th>Бренд</th><th>Номер</th><th>Тип</th><th>Источники</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="4">Ничего не найдено</td></tr>'}</tbody></table></div>`;
}

$('#btn-upload').onclick = async () => {
  const f = $('#file').files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('file', f);
  fd.append('sources', chosenSources().join(','));
  $('#job-out').innerHTML = '<p class="hint">Загружаем…</p>';
  try {
    const job = await api('/api/v1/jobs/upload', { method: 'POST', body: fd });
    $('#job-out').innerHTML = `<p class="hint">Задание <code>${job.id}</code> создано, позиций: ${job.total}</p>`;
    refresh();
  } catch (e) {
    $('#job-out').innerHTML = `<p class="warn">Ошибка: ${e.message}</p>`;
  }
};

async function refresh() {
  try {
    const jobs = await api('/api/v1/jobs');
    $('#jobs').innerHTML = jobs.length
      ? `<table><thead><tr><th>ID</th><th>Файл</th><th>Прогресс</th><th>Статус</th><th></th></tr></thead><tbody>${
          jobs.map(jobRow).join('')}</tbody></table>`
      : '<p class="hint">Заданий пока нет.</p>';
  } catch (_) {}
}

function jobRow(j) {
  const pct = j.total ? Math.round((100 * j.done) / j.total) : 0;
  return `<tr><td><code>${j.id.slice(0, 8)}</code></td><td>${j.filename || '—'}</td>
    <td style="min-width:180px">${j.done}/${j.total}<div class="bar"><i style="width:${pct}%"></i></div></td>
    <td><span class="pill ${j.status === 'done' ? 'ok' : ''}">${j.status}</span></td>
    <td>${j.status === 'done'
      ? `<a href="/api/v1/jobs/${j.id}/export.xlsx">Скачать xlsx</a>`
      : ''}</td></tr>`;
}

refresh();
setInterval(refresh, 3000);
