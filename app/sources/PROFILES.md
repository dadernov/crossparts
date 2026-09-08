# profiles.json — как добавить каталог без кода

`profiles.json` описывает источники, которые парсятся браузером по CSS-селекторам.
Сейчас файл пуст: `jnbk` и `mintex` переписаны в полноценные HTTP-адаптеры
(`jnbk.py`, `mintex.py`), они быстрее и не требуют Chromium.

Профиль пригодится для нового сайта, у которого выдача рисуется JavaScript.
Поля записи:

| Поле | Смысл |
|---|---|
| `key`, `title`, `homepage` | идентификация источника |
| `search_url` | URL с плейсхолдером `{oe}` |
| `input_selector` | если задан — в поле вводится номер и жмётся Enter |
| `submit_selector` | кнопка отправки (если Enter не подходит) |
| `wait_selector` | чего ждать перед разбором; иначе ждём `wait_ms` |
| `row_selector` | строка выдачи |
| `brand_selector` / `number_selector` | бренд и номер внутри строки |
| `default_brand` | если бренд на странице не указан |
| `verified` | `true`, когда селекторы проверены на живом сайте |

Пример:

```json
[{
  "key": "example",
  "title": "Example catalogue",
  "homepage": "https://example.com/",
  "search_url": "https://example.com/search?q={oe}",
  "row_selector": "table.crosses tr",
  "brand_selector": "td:nth-child(1)",
  "number_selector": "td:nth-child(2)",
  "wait_ms": 4000,
  "verified": false
}]
```

Если у сайта есть нормальный HTTP-API или form-POST (как оказалось у jnbk),
лучше написать класс-наследник `BaseSource` — это ~80 строк и работает без браузера.
