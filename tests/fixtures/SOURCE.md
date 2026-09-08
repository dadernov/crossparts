# Откуда взяты фикстуры

Живые `jnbk-brakes.com` и `brakebook.com` закрыты для этого хоста на сетевом уровне
(403 AWS WAF и Cloudflare managed challenge соответственно), поэтому разметка снята
из Web Archive — это настоящий HTML этих сайтов, не выдумка:

| Файл | Источник |
|---|---|
| `jnbk_catalogue_cars.html` | `web.archive.org/web/20260513103543id_/https://www.jnbk-brakes.com/catalogue/cars` |
| `jnbk_product_RN2713.html` | `web.archive.org/web/20260513101521id_/https://jnbk-brakes.com/catalogue/cars/brake/101572196/RN2713` |
| `brakebook_datasheet_BPD2244.html` | `web.archive.org/web/20230201160954id_/http://www.brakebook.com/bb/bendix/de/BPD2244_402/datasheet.xhtml` |
| `brakebook_search.html` | `web.archive.org/web/20170720111322id_/http://www.mintex.brakebook.com/bb/don/en/applicationSearch.xhtml` |

Тесты `tests/test_sources_offline.py` парсят эти файлы и проверяют, что адаптеры
достают правильные кроссы. Так логика разбора проверена по-настоящему, и при
появлении доступа к сайтам останется только сетевой вопрос.

Фикстуры LUZAR и Nissens сняты с живых сайтов напрямую (оба доступны с этого хоста).
Страницы там тяжёлые — 279 КБ и 2,3 МБ, — поэтому в репозиторий положены срезы
настоящей разметки, а не весь документ:

| Файл | Источник |
|---|---|
| `luzar_product_LRc0938.html` | срез `luzar.ru/catalogue/radiatory/radiatory-okhlazhdeniya/radiator-okhlazhdeniya-logan-08-mt-lrc-0938/`: блок с артикулом и блок `div.list-oems` |
| `nissens_details_637609.html` | ответ `POST catalogue.nissens.com/Product/ProductDetails` для артикула 637609 целиком |
| `nissens_search_8200735038.html` | срез выдачи `POST catalogue.nissens.com/Product/Search` по ОЕ `8200735038`: одна ячейка `td.productlinks` |

Тесты: `tests/test_radiators.py`.

Фикстуры Brixo — ответы открытого API `brixogroup.com`, сохранены как есть:

| Файл | Источник |
|---|---|
| `brixo_search_58101H5A25.json` | `GET brixogroup.com/api/sku/search?search_string=58101H5A25` |
| `brixo_info_PN0537.json` | `GET brixogroup.com/api/sku/info/PN0537` (колодки NiBK) |
| `brixo_info_3631-1002.json` | `GET brixogroup.com/api/sku/info/3631-1002` (радиатор SAKURA) |

Тесты: `tests/test_brixo.py`.

| `kyb_cross_4851080378.json` | `POST kyb.ru/api/2/cross`, тело `{"partNumber":"4851080378"}` — тесты `tests/test_kyb.py` |
| `hola_search_58101H5A25.html` | срез выдачи `hola-auto.ru/production/search-cross/58101H5A25/` |
| `hola_product_BD836.html` | вкладка «Номера оригинальных деталей» карточки `hola-auto.ru/production/brake-pads-and-shoes/BD836/` — тесты `tests/test_hola.py` |
| `brannor_search_8K0698451D.html` | ссылки выдачи `brannor.ru/search-oem/?search=8K0698451D` |
| `brannor_product_BRP1386A.html` | блок `ol.oems` карточки BRP1386A — тесты `tests/test_brannor.py` |
| `hel_search_1K0611701.html` | карточка выдачи `helrussia.ru/index.php?route=product/search&search=1K0611701` — тесты `tests/test_hel.py` |
