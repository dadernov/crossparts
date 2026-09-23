# Создание аккаунтов CrossParts

Правило для обычных пользовательских аккаунтов с общим лимитом поисковых позиций. Специальные режимы пакетной обработки и замедления настраиваются отдельно и не включаются автоматически при создании пользователя.

## Что нужно получить от пользователя

- логин;
- общий лимит поисковых позиций;
- отдельные ограничения или режимы — только если они явно запрошены.

Если длина пароля не указана, генерировать **10 символов**: латинские буквы обоих регистров и цифры. Пароль не вводить вручную и не сохранять в репозитории.

## Источник данных

- Рабочий сервис использует переменные из `/root/crossparts/.env.production`.
- Фактический URL базы берётся из `CP_DATABASE_URL`; нельзя предполагать путь к БД по `.env` для разработки.
- Аккаунт хранится в таблице `accounts`, модель — [`app/models.py`](../app/models.py), класс `Account`.
- Пароль хранится только как результат `hash_password()` из [`app/security.py`](../app/security.py).
- Лимит аккаунта задаётся в `queries_limit`; новый аккаунт получает `queries_used = 0`.
- Один исходный номер расходует одну позицию лимита. Лимит обычного аккаунта общий, а не ежедневный.

## Правильная процедура

1. Перейти в `/root/crossparts` и убедиться, что `crossparts.service` действительно использует `.env.production`.
2. Нормализовать логин: убрать пробелы и привести к нижнему регистру. Допустимый формат: `a-z`, `0-9`, `_`, `-`; длина от 3 до 64 символов.
3. Проверить, что аккаунта с таким логином ещё нет. Существующий аккаунт не перезаписывать и не обнулять.
4. Сгенерировать пароль внутри процесса через `secrets`, создать хеш через `hash_password()` и добавить `Account` одной транзакцией.
5. Проверить сохранённые `username`, `queries_limit`, `queries_used`, длину пароля и успешную `authenticate()`.
6. Передать пользователю логин, пароль, лимит и текущее использование. Пароль показывается только в результате создания.

Рекомендуемая команда для обычного аккаунта:

```bash
cd /root/crossparts
set -a
source .env.production
set +a
USER_LOGIN=example USER_LIMIT=100 python3 - <<'PY'
import asyncio
import os
import re
import secrets

from app.db import SessionLocal, engine
from app.models import Account
from app.security import authenticate, check_password, hash_password


login = os.environ["USER_LOGIN"].strip().lower()
limit = int(os.environ["USER_LIMIT"])

if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", login):
    raise SystemExit("Некорректный логин")
if limit <= 0:
    raise SystemExit("Лимит должен быть больше нуля")

alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
while True:
    password = "".join(secrets.choice(alphabet) for _ in range(10))
    if (
        any(char.islower() for char in password)
        and any(char.isupper() for char in password)
        and any(char.isdigit() for char in password)
    ):
        break


async def main():
    async with SessionLocal() as session:
        if await session.get(Account, login) is not None:
            raise SystemExit("Аккаунт уже существует; запись не изменена")

        password_hash = hash_password(password)
        if not check_password(password, password_hash):
            raise SystemExit("Не удалось проверить новый хеш")

        account = Account(
            username=login,
            password_hash=password_hash,
            queries_used=0,
            queries_limit=limit,
        )
        session.add(account)
        await session.commit()

    if await authenticate(SessionLocal, login, password) != login:
        raise SystemExit("Аккаунт создан, но проверка входа не прошла")

    async with SessionLocal() as session:
        account = await session.get(Account, login)
        assert account is not None
        assert account.queries_limit == limit
        assert account.queries_used == 0

    print(f"LOGIN={login}")
    print(f"PASSWORD={password}")
    print(f"LIMIT={limit} USED=0 PASSWORD_LENGTH={len(password)} HASH_OK=true")
    await engine.dispose()


asyncio.run(main())
PY
```

Вместо `example` и `100` подставляются согласованные логин и лимит. Пароль в команду не передаётся: он генерируется внутри Python и поэтому не остаётся в shell history.

## Что не делать

- не хранить открытый пароль в `.env`, исходниках, Markdown, логах или Git;
- не добавлять постоянный аккаунт в `CP_USERS`: это bootstrap-механизм, а лимит созданной записи всё равно живёт в БД;
- не писать открытый пароль в `password_hash`;
- не изменять `queries_used` существующего аккаунта без отдельной просьбы;
- не удалять и не пересоздавать аккаунт для смены пароля или лимита;
- не добавлять пользователя в `CP_JOB_CHUNK_SIZES` или `CP_PACED_TENANTS`, если специальные режимы явно не запрошены;
- не перезапускать сервис после обычной записи в БД: новый аккаунт доступен сразу;
- не коммитить `data/crossparts.db` и не создавать коммит для операции с рабочими данными.

## Специальные режимы

- Разбиение Excel на отдельные задания задаётся через `CP_JOB_CHUNK_SIZES`, например `login:50`.
- Искусственное замедление задаётся через `CP_PACED_TENANTS` и общие параметры pacing.
- Эти настройки требуют отдельного согласованного изменения production-конфигурации и перезапуска сервиса.
- Перед включением нужно проверить, не затронуты ли другие аккаунты общими значениями pacing.
