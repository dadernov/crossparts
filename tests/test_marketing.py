"""Public pages use real routes, assets and browser interactions without production data."""
import asyncio
import mimetypes
from pathlib import Path
import httpx
import pytest
from playwright.sync_api import sync_playwright
from app import main

PATHS = ['/features', '/categories', '/pricing', '/integrations', '/contacts', '/demo']

async def public_pages():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://marketing.local') as client:
        pages = {}
        for path in PATHS:
            response = await client.get(path)
            assert response.status_code == 200, path
            pages[path] = response.text
        return pages


def test_public_content():
    pages = asyncio.run(public_pages())
    for count in ['40', '120', '250']:
        assert f'<strong>{count}</strong>' in pages['/pricing']
    for price in ['20 000', '50 000', '100 000']:
        assert price in pages['/pricing']
    assert pages['/categories'].count('class="surface category-card"') == 5
    for link in ['tel:+79998049374', 'mailto:info@mrbdigital.ru', 'https://t.me/mrbdigital']:
        assert link in pages['/contacts']
    assert 'Пн–Пт с 10:00 до 19:00 (МСК)' in pages['/contacts']
    assert len(set(pages.values())) == len(PATHS)


@pytest.mark.parametrize('browser_name',['chromium','webkit'])
def test_marketing_browser(browser_name):
    pages = asyncio.run(public_pages())
    with sync_playwright() as p:
        browser = getattr(p,browser_name).launch()
        page = browser.new_page(viewport={'width':1440,'height':900})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            path=r.request.url.split('https://marketing.local')[-1].split('?')[0]
            if path.startswith('/static/'):
                file=Path('app'+path)
                assert file.is_file(),path
                r.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
            elif path=='/trial':r.fulfill(body='<h1>Пробный поиск</h1>',content_type='text/html')
            elif path=='/login':r.fulfill(body='<h1>Вход</h1>',content_type='text/html')
            else:
                assert path in pages,path
                r.fulfill(body=pages[path],content_type='text/html')
        page.route('**/*',route)
        for path in PATHS:
            page.goto('https://marketing.local'+path)
            page.evaluate('document.fonts.ready')
            assert page.locator('h1').count()==1
            assert page.locator('img').evaluate_all('(images)=>images.every(i=>i.complete && i.naturalWidth>0)')
            for width in [320,390,768,1440]:
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(path,width)
            for href in page.locator('a[href^="/"]').evaluate_all('(els)=>els.map(e=>e.getAttribute("href").split("?")[0])'):
                assert href in {'/', '/login'} or href in pages or href.startswith('/static/'),href
            if browser_name=='chromium':
                out=Path('output/welcome-site');out.mkdir(exist_ok=True)
                page.screenshot(path=str(out/(('welcome' if path=='/' else path[1:])+'.png')),full_page=True)
        page.goto('https://marketing.local/features')
        page.get_by_role('link',name='Категории',exact=True).click()
        assert page.url.endswith('/categories')
        page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async v=>{window.copied=v}}})")
        page.get_by_role('button',name='Копировать 58101H5A25',exact=True).click()
        assert page.evaluate('window.copied')=='58101H5A25'
        page.get_by_role('link',name='Войти',exact=True).click()
        assert page.url.endswith('/login')
        assert not errors
        browser.close()
