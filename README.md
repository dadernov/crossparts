# CrossParts — сервис поиска кроссов автозапчастей

MVP B2B-SaaS: на вход подаётся **оригинальный номер (OE)**, на выходе —
**все кросс-номера**, собранные из каталогов-источников, в двух форматах,
которые заказчик описал в тестовом файле `Тест - парсинг кроссов.xlsx`:

* **Вариант 1** — одна строка на кросс: `наш артикул | товарная группа | номер ОЕ | бренд | номер | тип | источники`
* **Вариант 2** — одна строка на артикул: `наш артикул | товарная группа | номер ОЕ | кол-во | все кроссы через запятую`

Сервис **работает на живых данных**, не на моках.

---

## 1. Быстрый старт

```bash
cd crossparts
python3 -m pip install -r requirements.txt
python3 -m playwright install --with-deps chromium   # нужен только для browser-источников
cp .env.example .env
./run.sh
```

* UI — <http://localhost:8000/>
* OpenAPI/Swagger — <http://localhost:8000/docs>

Прогнать файл заказчика без сервера:

```bash
python3 scripts/run_file.py "../Тест - парсинг кроссов.xlsx" out/result.xlsx
```

---

## 2. Товарные группы и источники

Заказчик присылает позиции с товарной группой (файл «Парсинг кроссов GERAT —
пошагово.xlsx»), а сайты в его таблице расписаны по группам. Сервис сводит одно
с другим: позиция ищется **только в каталогах своей группы** — искать колодки в
каталоге радиаторов бессмысленно и стоит лишних запросов.

Группы и покрытие видны в UI и через `GET /api/v1/groups`:

| Группа | Готово | Заблокировано | В планах |
|---|---|---|---|
| Тормозные колодки | SB NAGAMOCHI, Brembo, TRIALLI | NIBK, Mintex | ATE, ZIMMERMANN, BRANNOR, FAP, MONAER, NIBK(ru) |
| Тормозные диски | SB NAGAMOCHI, Brembo, TRIALLI | NIBK, Mintex | те же |
| Тормозные шланги | TRIALLI | — | PATRON, HEL, TRW, STELLOX |
| Амортизаторы | TRIALLI | — | KYB, Bilstein, SACHS, BOGE, KONI, HOLA |
| Радиаторы охлаждения | — | — | Nissens, LUZAR, SALURA, NRF, AVA |

Полный список из файла заказчика — в
[`app/sources/catalog.json`](app/sources/catalog.json): бренд, группы, URL и статус
(`implemented` / `blocked` / `planned`). Группа позиции распознаётся по названию
(`app/groups.py`), незнакомая — не выдумывается, а показывается как прислали.

| Ключ | Каталог | Группы | Статус |
|---|---|---|---|
| `sbparts` | SB NAGAMOCHI — sbparts.ru | колодки, диски | **проверен на живых данных** |
| `brembo` | Brembo — bremboparts.com | колодки, диски | **проверен на живых данных** |
| `trialli` | TRIALLI — trialli.ru | колодки, диски, шланги, амортизаторы | **проверен на живых данных** |
| `jnbk` | NIBK — jnbk-brakes.com | колодки, диски | парсер готов, нужен доступ по IP |
| `mintex` | Mintex — brakebook.com | колодки, диски | парсер готов, нужен доступ по IP |

### Как устроен каждый рабочий парсер

**sbparts** (`app/sources/sbparts.py`)
1. `POST /wp-admin/admin-ajax.php` с `action=search_submit&sku=<OE>` — отдаёт HTML-карточки
   найденных товаров со ссылками `/catalog/<SKU>`.
2. Страница товара содержит таблицу «Номера аналогов» — пары `бренд + номер`.

**trialli** (`app/sources/trialli.py`) — Bitrix, поиск обычным GET:
1. `GET /catalogue/?q=<номер>` — выдача со ссылками на карточки.
2. На карточке блок «ОЕМ-номер»: `div.detail_main_oem[data-code]`.
Покрывает четыре группы из пяти — самый широкий источник.

**brembo** (`app/sources/brembo.py`)
1. `GET /europe/ru` — забираем cookie `aft` и скрытое поле `__RequestVerificationToken`.
   *Без заголовка `RequestVerificationToken` все API-роуты Brembo отвечают 404* — это
   и есть основная «защита» их каталога.
2. `POST /europe/ru/catalogue/search/searchcode` → `{"url": "/…/code?code=…"}`.
   Номер не из каталога → `400 {"Code":["Код изделия недействителен"]}` → трактуем как `not_found`.
3. На странице результатов берём коды Brembo (`P 30 122`).
4. По каждому коду: `getproductmanufacturerreferences` (OE-номера) и
   `getproductcompetitorreferences` (номера конкурентов).

### jnbk и mintex

**Разбор написан и проверен, упирается только в IP.**

Оба домена отдают блокировку **на сетевом уровне, до любого HTML**:

```
jnbk-brakes.com      → HTTP 403 от awselb/2.0 даже на /robots.txt
mintex.brakebook.com → HTTP 403, cf-mitigated: challenge (Cloudflare managed challenge)
```

Проверено обычным HTTP-клиентом, headless-Chromium и headful-Chromium под Xvfb:
блокировка по репутации IP, кодом не обходится.

Чтобы это не было тупиком, разметку и механику обоих сайтов сняли из Web Archive
(настоящий HTML этих сайтов, см. [`tests/fixtures/SOURCE.md`](tests/fixtures/SOURCE.md))
и написали по ней полноценные парсеры:

**jnbk** (`app/sources/jnbk.py`) — оказалось, что поиск там обычная form-POST,
браузер не нужен вовсе:
1. `POST /catalogue/cars` с полями `txtPartNo` / `txtClass=1` / `btnProductSearch`.
2. Ответ — карточка товара либо список ссылок `/catalogue/cars/brake/<id>/<артикул>`.
3. На карточке блок «Cross Reference»: `div.detail__plate` → `.str` → `.owner` + `.field`.

**mintex** (`app/sources/mintex.py`) — brakebook это JSF-приложение TMD Friction:
1. `GET /bb/mintex/ru/applicationSearch.xhtml` — сессия и `javax.faces.ViewState`.
2. `POST /bb/public/applicationSearch.xhtml` формой `searchByKeywordsForm`
   (поле `search_keywords`).
3. Даташит открывается stateless-ссылкой `/bb/<config>/<locale>/<АРТИКУЛ>/datasheet.xhtml`,
   там блок «OE-Referenzen»: `div.relationTableCR table.af_table_content tr`
   с `td.manufacturer` и `td.name div.objectCode`.

Тесты `tests/test_sources_offline.py` прогоняют эти парсеры по сохранённой
разметке: из карточки NiBK достаются 4 кросса, из даташита brakebook — 72.

### Что нужно, чтобы включить их вживую: какой брать прокси

Прогнали оба домена через 40 проверочных узлов check-host.net в разных странах —
и получили два разных ответа.

**jnbk — блокировка по хостеру, не по стране.** 25 узлов из 40 получили `200`,
15 — `403`, и это никак не коррелирует с географией:

| Отвечает `200` | Отдаёт `403` |
|---|---|
| Франция (Scaleway, AS12876) | Германия (Hetzner, AS24940) |
| Швейцария (Init7, AS13030) | Финляндия (Hetzner, AS24940) |
| Канада, Япония, Гонконг, Индонезия | Нидерланды (AS14576), Сингапур |
| Иран, Турция, Индия — обычные ISP | Россия (Москва, СПб — оба на VPS-хостерах) |
| США: Даллас, Атланта, Майами | США: Нью-Йорк (AS213535) |

Один и тот же ASN (AS26141) прошёл из Майами и не прошёл из Барселоны — значит
фильтр **по конкретным IP**, а не по сети. Это поведение AWS WAF со списком
`AnonymousIpList` (адреса VPN, прокси и хостингов). Вывод: **локация свободная,
важно лишь чтобы IP не числился хостинговым**. Резидентный прокси в любой стране
подойдёт; из дата-центров сегодня проходили Scaleway (Париж) и Init7 (Цюрих),
но это лотерея — список AWS обновляется.

**mintex — локация не поможет вообще.** `403` со **всех 40 узлов**, включая те,
что спокойно открыли jnbk. Проверили и настоящим браузером с чужого облачного
адреса — тоже упирается в challenge. Cloudflare здесь режет любой не-резидентный
IP независимо от страны. Нужен **резидентный или мобильный** прокси; страна
роли не играет, разумно взять Россию или ЕС — ближе к вашим пользователям.

Итого:

| Источник | Что брать | Страна |
|---|---|---|
| `jnbk` | любой IP не из списка хостингов; резидентный — надёжнее | любая |
| `mintex` | только резидентный / мобильный | любая, удобнее РФ или ЕС |

Один резидентный прокси закрывает оба источника — отдельные брать не нужно.

### Сколько трафика нужно (важно: прокси тарифицируется по гигабайтам)

Замерено на живых запросах: один номер — это ~130 КБ у `jnbk` и ~150 КБ у `mintex`.
Проход Cloudflare стоит отдельно ~1.6 МБ, но решается раз в 20 минут на сессию,
а не на каждый запрос.

| Пакет | Трафик через прокси |
|---|---|
| 100 артикулов | ~0.03 ГБ |
| 1 000 артикулов | **~0.27 ГБ** |
| 5 000 артикулов | ~1.35 ГБ |

То есть минимального пакета в 1 ГБ хватает примерно на 3–4 тысячи артикулов.
Большой тариф брать незачем.

Что для этого сделано в коде:

* `ClearanceStore` — cookies `cf_clearance` переиспользуются между запросами.
  Без этого challenge решался бы на каждый номер: 1.6 МБ × N вместо 1.6 МБ × 3.
* Предохранитель: после двух неудачных проходов подряд браузер не запускается
  10 минут. На неподходящем прокси сервис не сожжёт трафик впустую — сразу
  отвечает `blocked` (проверено: третий запрос возвращается за 0.1 с вместо 12 с).

### Проверка прокси до покупки

У большинства провайдеров есть триал. Проверяется одной командой:

```bash
python3 scripts/check_proxy.py http://user:pass@proxy-host:port
```

```
источник  вердикт         кроссов  время    комментарий
sbparts   РАБОТАЕТ        82         2110ms  источник отдал кроссы — можно включать
brembo    РАБОТАЕТ        107         401ms  источник отдал кроссы — можно включать
jnbk      ЗАБЛОКИРОВАН    0           668ms  нужен другой выходной IP
mintex    ЗАБЛОКИРОВАН    0         13063ms  домен закрыт Cloudflare для этого IP
```

Скрипт сам печатает строки для `.env`, которые надо скопировать. Дальше:

```ini
CP_PROXY_URL=http://user:pass@proxy-host:port
CP_PROXY_SOURCES=jnbk,mintex      # платный трафик только на них
CP_ENABLED_SOURCES=sbparts,brembo,jnbk,mintex
```

`CP_PROXY_SOURCES` важен: `sbparts` и `brembo` доступны напрямую, гонять их через
метрический прокси незачем. После правки — `systemctl restart crossparts`.
Когда источник заработает, поставьте `verified = True` в его классе.

### Бесплатный вариант: свой интернет вместо прокси

Домашний и мобильный IP уже резидентные. Сервер не может подключиться к ним
напрямую (NAT/CGNAT), поэтому соединение поднимает ваша машина — обратным
SSH-туннелем:

```
Домашний ПК / телефон                    Сервер
 SOCKS5 :1080  ◄──── ssh -R ────  127.0.0.1:1081 → CP_PROXY_URL
 (резидентный IP)   (исходящее)
```

Готовый комплект — в [`deploy/home-tunnel/`](deploy/home-tunnel/README.md):
скрипт с автопереподключением, systemd-юнит и инструкции для Linux, macOS,
Windows и Android (Termux, мобильный IP оператора).

На сервере уже заведён пользователь `tunnel`: без шелла, с `PermitOpen`
только на порт 1081. Проброс слушает на `127.0.0.1`, наружу прокси не торчит.
Остаётся добавить свой публичный ключ в `/home/tunnel/.ssh/authorized_keys`
с префиксом `restrict,port-forwarding`.

Проверено целиком: SOCKS5 → обратный туннель → ограниченный пользователь →
источники, включая браузерный проход Cloudflare (он тоже идёт через туннель).
Для SOCKS нужен пакет `httpx[socks]`, он в `requirements.txt`.

Ограничения: парсинг идёт с вашего адреса, скорость упирается в домашний
канал, выключили машину — источники отвалятся с внятным сообщением
«прокси … недоступен», а `sbparts` и `brembo` продолжат работать напрямую.

### Cloudflare: прокси мало, нужен браузер

`mintex` за managed challenge, который решается только исполнением JavaScript.
Поэтому адаптер работает в два шага: обычный HTTP-запрос, а если пришёл challenge —
Chromium проходит его через тот же прокси, и его cookies переносятся в HTTP-клиент
(`BaseSource.browser_cookies`). Отключается флагом `CP_BROWSER_FALLBACK=false`.

Заглушку ловим по структурному признаку (`/cdn-cgi/challenge-platform/`, `_cf_chl_opt`),
а не по тексту: Cloudflare локализует страницу, и с русской «Один момент…»
англоязычные маркеры не срабатывали — сервис счёл бы, что защита пройдена, и вернул
бы «ничего не найдено» вместо «заблокировано». Случай закрыт тестом на реальной
сохранённой странице.

---

## 3. API

Веб-интерфейс защищён логином и паролем: каждая учётная запись видит только свои
задания. Учётные записи задаются при развёртывании в `CP_USERS` в формате
`login:password,another:password`; при первом запуске есть `admin:changeme`, его
нужно заменить. API по-прежнему поддерживает `X-API-Key` (пары «ключ:тенант» в
`CP_API_KEYS`). Задания изолированы по тенанту.

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/v1/sources` | список источников, их группы и статус |
| `GET` | `/api/v1/groups` | товарные группы и покрытие каталогами |
| `POST` | `/api/v1/lookup` | синхронный поиск по одному номеру |
| `POST` | `/api/v1/jobs` | пакетное задание из JSON |
| `POST` | `/api/v1/jobs/upload` | пакетное задание из xlsx |
| `GET` | `/api/v1/jobs` | список заданий тенанта |
| `GET` | `/api/v1/jobs/{id}` | статус и прогресс |
| `GET` | `/api/v1/jobs/{id}/results?format=long\|wide` | результат в JSON (вариант 1 / вариант 2) |
| `GET` | `/api/v1/jobs/{id}/export.xlsx` | выгрузка в Excel |
| `GET` | `/healthz` | проба живости (без авторизации) |

```bash
# один номер
curl -s -X POST http://localhost:8000/api/v1/lookup \
  -H 'X-API-Key: demo-key' -H 'Content-Type: application/json' \
  -d '{"oe":"58101H5A25"}'

# пакет из файла
curl -s -X POST http://localhost:8000/api/v1/jobs/upload \
  -H 'X-API-Key: demo-key' \
  -F 'file=@Тест - парсинг кроссов.xlsx' -F 'sources=sbparts,brembo'

# выгрузка
curl -s -H 'X-API-Key: demo-key' \
  http://localhost:8000/api/v1/jobs/<id>/export.xlsx -o result.xlsx
```

Ответ `/lookup`:

```json
{
  "oe": "58101H5A25",
  "status": "ok",
  "crosses": [{"brand":"HYUNDAI","number":"58101-H5A25","kind":"oem","sources":["sbparts","brembo"]}],
  "unique_numbers": ["..."],
  "sources": [{"source":"sbparts","status":"ok","crosses":82,"elapsed_ms":2031}]
}
```

Статусы источника: `ok`, `not_found`, `blocked`, `error` — сервис **никогда не выдаёт
блокировку за «ничего не найдено»**, это разные вещи и обе видны в отчёте.

---

## 4. Как устроено внутри

```
app/
  main.py          FastAPI: UI + REST
  aggregator.py    параллельный опрос источников, дедупликация, кэш
  jobs.py          фоновый воркер пакетных заданий (asyncio + SQLite)
  excel.py         чтение входного xlsx и сборка выходного (3 листа + параметры)
  normalize.py     нормализация номеров и брендов
  models.py        Job / JobItem / CacheEntry
  security.py      X-API-Key → тенант
  sources/
    base.py        интерфейс адаптера, Cross / SourceResult
    sbparts.py     ─┐
    brembo.py       │ HTTP-парсеры каталогов
    jnbk.py         │ (sbparts и brembo проверены вживую,
    mintex.py      ─┘  jnbk и mintex — по сохранённой разметке)
    generic.py     browser-парсер, управляемый профилем
    profiles.json  описания сайтов для будущих каталогов на JS
    registry.py    сборка и выбор источников
```

Ключевые решения:

* **Ключ номера.** `58101-H5A25`, `58101 h5a25` и `58101H5A25` — один и тот же номер.
  Сравнение идёт по `number_key()` (только буквы и цифры, верхний регистр), а в выгрузку
  попадает человекочитаемая запись.
* **Дедупликация с сохранением происхождения.** Один и тот же кросс из двух каталогов
  даёт одну строку и список источников — заказчик видит, чем номер подтверждён.
* **Бренды.** Ячейка `HYUNDAI / KIA` разворачивается в два бренда, а `BECK/ARNLEY`
  остаётся одним (слэш без пробелов). `GEELY, GEOMETRY` — тоже два.
* **Кэш.** Ответы `ok` / `not_found` кэшируются в SQLite на `CP_CACHE_TTL_HOURS` (по
  умолчанию 7 дней). `blocked` и `error` не кэшируются — их надо перезапрашивать.
* **Вежливость.** Своя семафора на каждый источник (`CP_SOURCE_CONCURRENCY`), так что
  каталоги опрашиваются параллельно друг с другом, но не долбятся изнутри.
* **Устойчивость.** Задания лежат в БД; после перезапуска недоделанные подхватываются заново.

## 5. Конфигурация

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `CP_API_KEYS` | `demo-key:Demo` | `ключ:тенант` через запятую; пусто = без авторизации |
| `CP_ENABLED_SOURCES` | `sbparts,brembo` | источники по умолчанию |
| `CP_PROXY_URL` | — | прокси для HTTP и Chromium (`http`/`https`/`socks5`) |
| `CP_PROXY_SOURCES` | — | какие источники пускать через прокси; пусто = все |
| `CP_BROWSER_FALLBACK` | `true` | проходить Cloudflare-challenge браузером и переиспользовать cookies |
| `CP_SOURCE_TIMEOUT` | `45` | таймаут одного источника, сек |
| `CP_JOB_CONCURRENCY` | `4` | параллельных заданий |
| `CP_SOURCE_CONCURRENCY` | `2` | параллельных запросов к одному источнику |
| `CP_CACHE_TTL_HOURS` | `168` | время жизни кэша |
| `CP_MAX_PRODUCTS_PER_OE` | `5` | сколько товаров источника разбирать на один OE |
| `CP_DATABASE_URL` | `sqlite+aiosqlite:///./data/crossparts.db` | БД (совместимо с Postgres) |

## 6. Тесты

```bash
python3 -m pytest tests -q          # юнит-тесты
CP_LIVE=1 python3 -m pytest tests -q  # + живые запросы к sbparts и brembo
```

Сверка с эталоном из файла заказчика:

```bash
python3 scripts/run_file.py "../Тест - парсинг кроссов.xlsx" out/result.xlsx
python3 scripts/compare_with_reference.py
```

## 7. Боевой стенд

Сервис развёрнут и доступен по адресу **<https://mrb-cross-search-test.duckdns.org/>**
(HTTP автоматически редиректит на HTTPS).

| Компонент | Что делает |
|---|---|
| `crossparts.service` | uvicorn на `127.0.0.1:8000`, автозапуск и авто-рестарт |
| nginx | реверс-прокси на 80/443, TLS, rate limit, приём xlsx до 20 МБ |
| Let's Encrypt | сертификат на домен, продление через штатный `certbot.timer` |
| `duckdns.timer` | раз в 15 минут обновляет A-запись, если сменится IP машины |

Конфиги лежат в [`deploy/`](deploy/) — это копии того, что реально стоит в системе:

```
deploy/crossparts.service      → /etc/systemd/system/
deploy/duckdns.service|.timer  → /etc/systemd/system/
deploy/duckdns-update.sh       → скрипт обновления DNS
deploy/nginx-crossparts.conf   → /etc/nginx/sites-available/crossparts
deploy/nginx-limits.conf       → /etc/nginx/conf.d/crossparts-limits.conf
deploy/nginx-proxy-snippet.conf→ /etc/nginx/snippets/crossparts-proxy.conf
```

Токен DuckDNS хранится в `deploy/duckdns.env` (права `600`, в git не попадает).
Настройки боевого запуска — в `.env.production` (тоже вне git).

### Эксплуатация

```bash
systemctl status crossparts          # состояние
systemctl restart crossparts         # перезапуск после правки кода
journalctl -u crossparts -f          # или tail -f /var/log/crossparts.log
tail -f /var/log/nginx/crossparts.access.log
certbot renew --dry-run              # проверить продление сертификата
```

### Доступ и защита

Сейчас демо **открыто по ссылке без пароля** — чтобы её можно было просто отправить
клиенту. Злоупотребление ограничено на уровне nginx:

* `POST` (то, что реально ходит во внешние каталоги) — 30 запросов в минуту с IP,
  burst 10, сверх лимита `429`;
* `GET` (опрос статуса задания из UI) под строгий лимит не попадает;
* не более 20 одновременных соединений с одного IP.

Закрыть доступ, когда демо отработает:

```bash
# вариант 1 — ключ для API
sed -i 's/^CP_API_KEYS=.*/CP_API_KEYS=<ключ>:<клиент>/' /root/crossparts/.env.production
systemctl restart crossparts

# вариант 2 — общий пароль на весь сайт
apt-get install -y apache2-utils
htpasswd -c /etc/nginx/.htpasswd demo
# в server{} блока 443 добавить:
#   auth_basic "CrossParts"; auth_basic_user_file /etc/nginx/.htpasswd;
systemctl reload nginx
```

## 8. Что дальше до продакшена

1. Подключить egress-прокси и включить `jnbk` + `mintex` — код готов, см. раздел 2.
2. Postgres вместо SQLite и Celery/RQ вместо in-process воркера при росте объёма.
3. Тарификация и лимиты на тенанта (сейчас есть только ключ и изоляция заданий).
4. Расширить список брендов-афтермаркета в `normalize.py` — от него зависит колонка «Тип».
5. Автопривязка найденных кроссов к артикулам заказчика (в чате: «к ним мы потом сами всё подтянем»).
