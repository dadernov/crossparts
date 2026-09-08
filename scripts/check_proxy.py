#!/usr/bin/env python3
"""Проверить прокси до покупки: пустит ли его каждый из каталогов.

    python3 scripts/check_proxy.py                          # без прокси, как есть сейчас
    python3 scripts/check_proxy.py http://user:pass@host:port
    python3 scripts/check_proxy.py socks5://host:1080 --sources jnbk,mintex

Выводит по каждому источнику статус и подсказку, что делать дальше.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

VERDICT = {
    "ok": ("РАБОТАЕТ", "источник отдал кроссы — можно включать"),
    "not_found": ("ДОСТУПЕН", "сайт ответил, но по этому номеру ничего нет — возьмите другой номер"),
    "blocked": ("ЗАБЛОКИРОВАН", "нужен другой выходной IP"),
    "error": ("ОШИБКА", "смотрите сообщение"),
}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proxy", nargs="?", default="", help="URL прокси; без него — прямое соединение")
    ap.add_argument("--sources", default="sbparts,brembo,jnbk,mintex")
    ap.add_argument("--oe", default="58101H5A25", help="номер для пробы")
    args = ap.parse_args()

    # Настройки читаются из окружения, поэтому проставляем до импорта конфига.
    os.environ["CP_PROXY_URL"] = args.proxy
    os.environ["CP_PROXY_SOURCES"] = ""      # в проверке гоним через прокси всё
    from app.config import Settings
    from app.sources.registry import SourceRegistry

    settings = Settings(proxy_url=args.proxy, proxy_sources="", api_keys="")
    registry = SourceRegistry(settings)

    print(f"Прокси : {args.proxy or '(нет, прямое соединение)'}")
    print(f"Номер  : {args.oe}\n")
    print(f"{'источник':<10}{'вердикт':<16}{'кроссов':<9}{'время':<9}комментарий")
    print("-" * 96)

    worked = []
    for key in [k.strip() for k in args.sources.split(",") if k.strip()]:
        source = registry.get(key)
        if source is None:
            print(f"{key:<10}{'НЕТ ТАКОГО':<16}")
            continue
        res = await source.lookup(args.oe)
        label, hint = VERDICT.get(res.status.value, (res.status.value, ""))
        note = (res.message or hint)[:44]
        print(f"{key:<10}{label:<16}{len(res.crosses):<9}{res.elapsed_ms:>6}ms  {note}")
        if res.status.value in ("ok", "not_found"):
            worked.append(key)

    await registry.close()

    print()
    if worked:
        print("Прошли:", ", ".join(worked))
        print("Включить их в .env:")
        print(f"  CP_ENABLED_SOURCES={','.join(dict.fromkeys(['sbparts', 'brembo', *worked]))}")
        if args.proxy:
            need = [k for k in worked if k in ("jnbk", "mintex")]
            if need:
                print(f"  CP_PROXY_URL={args.proxy}")
                print(f"  CP_PROXY_SOURCES={','.join(need)}")
    else:
        print("Ни один источник не прошёл — нужен другой прокси.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
