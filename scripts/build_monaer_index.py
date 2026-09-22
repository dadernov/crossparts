#!/usr/bin/env python3
"""Build a reviewed MONAER index from the public sitemap once, off the request path."""
from __future__ import annotations
import argparse, asyncio, hashlib, re
from pathlib import Path
import httpx
from app.sources.monaer import SITEMAP, build_sqlite_index, parse_product_page

async def main(output: Path):
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={'User-Agent':'CrossParts catalogue verification'}) as client:
        sitemap = await client.get(SITEMAP)
        sitemap.raise_for_status()
        urls = re.findall(r'<loc>(https://monaer-russia\.ru/catalog/tproduct/[^<]+)</loc>', sitemap.text)
        sem = asyncio.Semaphore(5)
        async def get(url):
            async with sem:
                try:
                    response = await client.get(url)
                    return parse_product_page(response.text, str(response.url)) if response.status_code == 200 else None
                except httpx.HTTPError:
                    return None
        parsed = await asyncio.gather(*(get(url) for url in urls))
    products = [item for item in parsed if item is not None]
    report = build_sqlite_index(products, output, source_hash=hashlib.sha256(sitemap.content).hexdigest())
    print({**report, 'sitemap_products': len(urls), 'rejected': len(urls)-len(products)})

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    args=parser.parse_args();asyncio.run(main(args.output))
