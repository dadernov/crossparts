# Свой интернет вместо платного прокси

У домашнего интернета и у мобильного оператора IP уже резидентные — ровно то,
что нужно `jnbk` и `mintex`. Платить не за что, надо лишь дать серверу
возможность через них выходить.

Прямо подключиться сервер не может: домашний роутер за NAT, мобильный оператор —
за CGNAT. Поэтому соединение поднимает **ваша** машина, наружу:

```
  Домашний ПК / телефон                      Сервер
  ┌──────────────────────┐                   ┌───────────────────────────┐
  │ SOCKS5 на :1080      │◄──── ssh -R ──────│ 127.0.0.1:1081            │
  │ (резидентный IP)     │   (исходящее      │ CP_PROXY_URL=socks5://... │
  └──────────────────────┘    от вас)        └───────────────────────────┘
```

Проброс слушает на `127.0.0.1` сервера — прокси не будет открыт наружу.
Ключ выдаётся пользователю `tunnel`, у которого нет шелла и разрешён только
этот один порт.

---

## Шаг 1. Ключ (на вашей машине)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/crossparts_tunnel -N ''
cat ~/.ssh/crossparts_tunnel.pub
```

Публичный ключ добавить на сервере (одна строка, префикс обязателен):

```bash
echo 'restrict,port-forwarding ssh-ed25519 AAAA... home-pc' \
  >> /home/tunnel/.ssh/authorized_keys
```

## Шаг 2. Локальный SOCKS5 (на вашей машине)

| ОС | Команда |
|---|---|
| Ubuntu/Debian | `sudo apt install microsocks` |
| macOS | `brew install microsocks` |
| Windows | проще через WSL, либо любой SOCKS-сервер, например 3proxy |

## Шаг 3. Туннель

```bash
SERVER=mrb-crossparts.ru ./tunnel.sh
```

Скрипт сам поднимает SOCKS5, держит соединение и переподключается при обрывах
домашнего интернета.

Чтобы туннель жил без вашего участия:

```bash
mkdir -p ~/crossparts-tunnel && cp tunnel.sh ~/crossparts-tunnel/
mkdir -p ~/.config/systemd/user && cp crossparts-tunnel.service ~/.config/systemd/user/
systemctl --user enable --now crossparts-tunnel
sudo loginctl enable-linger $USER      # работать и без входа в систему
```

## Шаг 4. Включить на сервере

```ini
CP_PROXY_URL=socks5://127.0.0.1:1081
CP_PROXY_SOURCES=jnbk,mintex
CP_ENABLED_SOURCES=sbparts,brembo,jnbk,mintex
```

```bash
systemctl restart crossparts
python3 scripts/check_proxy.py socks5://127.0.0.1:1081
```

---

## Вариант с телефоном (мобильный IP)

Мобильный IP оператора надёжнее домашнего: его почти никогда не числят
хостинговым. Нужен Android с интернетом.

1. Поставить **Termux** (F-Droid, не Play Market — там версия устарела).
2. В Termux:

   ```bash
   pkg update && pkg install openssh microsocks
   ssh-keygen -t ed25519 -f ~/.ssh/crossparts_tunnel -N ''
   cat ~/.ssh/crossparts_tunnel.pub     # добавить на сервер, как в шаге 1
   ```
3. Запуск:

   ```bash
   microsocks -i 127.0.0.1 -p 1080 &
   ssh -N -i ~/.ssh/crossparts_tunnel \
       -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
       -R 127.0.0.1:1081:127.0.0.1:1080 tunnel@mrb-crossparts.ru
   ```
4. Чтобы Android не убивал Termux: `termux-wake-lock`, плюс отключить
   оптимизацию батареи для Termux в настройках.

Телефон должен сидеть на **мобильном интернете**, а не на домашнем Wi-Fi —
иначе получится тот же домашний IP.

---

## Windows без WSL

OpenSSH встроен в Windows 10/11, отдельный SOCKS-сервер всё же нужен
(например 3proxy). После установки:

```powershell
ssh -N -i $env:USERPROFILE\.ssh\crossparts_tunnel `
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 `
    -R 127.0.0.1:1081:127.0.0.1:1080 tunnel@mrb-crossparts.ru
```

Автозапуск — через «Планировщик заданий», триггер «При входе в систему».

---

## Что имейте в виду

* **Весь парсинг пойдёт с вашего IP.** Для нескольких тысяч артикулов в день
  это незаметно, но это ваш домашний адрес в логах чужих сайтов.
* **Скорость упрётся в ваш upload.** Пакет на 1000 артикулов — это ~0.27 ГБ,
  на домашнем канале несколько минут.
* **Выключили ПК — источники отваливаются.** Сервис ответит
  `прокси … недоступен. Проверьте, что туннель поднят`, `sbparts` и `brembo`
  продолжат работать (они ходят напрямую, `CP_PROXY_SOURCES` это обеспечивает).
* Для демо клиентам это нормально. Для боевого SaaS с чужой нагрузкой —
  нет: тогда либо платный резидентный прокси, либо лицензия TecDoc.
