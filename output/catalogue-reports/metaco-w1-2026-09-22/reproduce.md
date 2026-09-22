# Воспроизведение проверки кандидата

Рабочая ветка: `catalogue-expansion`. Production не обновлялся.

1. Получить опубликованные производителем OEM и cross-list CSV с https://metaco.parts/content/downloads. Сверить SHA256 с `summary.json`; новый снимок требует повторной проверки эталонов.
2. Построить отдельный индекс:

```sh
python3 scripts/build_metaco_index.py --oem /tmp/metaco-oem.csv --replacements /tmp/metaco-replacements.csv --output /tmp/metaco-w1.sqlite3
python3 scripts/check_metaco_candidate.py --index /tmp/metaco-w1.sqlite3 --output output/catalogue-reports/metaco-w1-2026-09-22
CP_LIVE=0 python3 -m pytest -q -rs
```

`check_metaco_candidate.py` не создаёт аккаунты, не запускает сервер или очередь, не использует БД приложения и не обращается к сети. Он проверяет 40 случаев через разрешённый источник с точной группой, сравнивает исходные доказательства и объединённые пары, отдельно считает потери меток OEM/aftermarket при merge. Затем измеряет 200 повторов каждого из двух запросов и создаёт Excel для ручной проверки. Первые нули в номерах сохраняются.

Для отдельного staging-сервера нужны собственные SQLite, порт, session secret, аккаунт и два параметра:

```dotenv
CP_METACO_INDEX_PATH=/absolute/path/to/reviewed-metaco.sqlite3
CP_PILOT_RULES={"metaco":{"groups":["brake_pads","brake_discs"],"tenants":["pilot-account"],"default":true}}
```

Одиночный запрос обязательно передаёт `group`; Excel — колонку «Товарная группа». Без группы METACO не запускается. Явный `sources=["metaco"]` не обходит ограничения аккаунта/группы. Выключение: очистить `CP_PILOT_RULES` при следующем управляемом запуске staging. Не применять этот пример к production: сначала устранить блокеры из release.md и пройти G5–G7.
