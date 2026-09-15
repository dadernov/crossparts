"""Authentication pages retain native password-manager form semantics."""
import asyncio
import mimetypes
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from app import main
from app.config import get_settings


def test_login_form_and_native_redirect(monkeypatch):
    async def authenticate(_session, username, password):
        return username if (username, password) == ('form-check', 'test-password') else None

    monkeypatch.setattr(main, 'authenticate', authenticate)

    async def check():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url='https://test.local') as client:
            response = await client.get('/login')
            assert response.status_code == 200
            assert 'id="guest-login"' in response.text
            assert 'action="/login" method="post" autocomplete="on"' in response.text
            assert 'name="username" autocomplete="username"' in response.text
            assert 'name="password" autocomplete="current-password"' in response.text
            response = await client.post('/login', data={'username': 'form-check', 'password': 'wrong-password'})
            assert response.status_code == 401
            assert 'Неверный логин или пароль' in response.text
            assert 'wrong-password' not in response.text
            assert 'id="guest-login"' in response.text
            response = await client.post('/login', data={'username': 'form-check', 'password': 'test-password'})
            assert response.status_code == 303
            assert response.headers['location'] == '/'
            assert 'crossparts_session' in client.cookies
            response = await client.get('/')
            assert response.status_code == 200
            assert 'id="lookup-form"' in response.text
            assert 'id="login-form"' not in response.text
            assert 'test-password' not in response.text

            await client.post('/logout')
            response = await client.get('/')
            assert response.status_code == 200
            assert 'id="lookup-form"' in response.text
            assert 'Не авторизован' in response.text
            assert 'Пробный доступ · 10 поисков' in response.text
            assert 'id="header-password"' in response.text

    asyncio.run(check())


def test_guest_account_menu_opens_native_login_and_trial():
    env = Environment(loader=FileSystemLoader('app/templates'), autoescape=True)
    html = env.get_template('index.html').render(
        username=None, is_guest=True, login_open=False, login_error=None,
        settings=get_settings(),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        def route(request):
            path = request.request.url.split('https://guest.local')[-1].split('?', 1)[0]
            if path.startswith('/static/'):
                file = Path('app' + path)
                request.fulfill(body=file.read_bytes(),
                                content_type=mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
            elif path == '/api/v1/account':
                request.fulfill(json={"limit": 10, "used": 0, "remaining": 10})
            elif path == '/api/v1/groups':
                request.fulfill(json={"groups": []})
            elif path == '/api/v1/sources':
                request.fulfill(json={"sources": [], "default": []})
            elif path.startswith('/api/v1/jobs'):
                request.fulfill(json=[])
            else:
                request.fulfill(body=html, content_type='text/html')

        page.route('**/*', route)
        page.goto('https://guest.local/')
        page.get_by_role('button', name='Не авторизован').click()
        page.get_by_role('button', name='Войти по логину и паролю').click()
        assert page.locator('#header-password').is_visible()
        assert page.locator('#header-password').get_attribute('autocomplete') == 'current-password'
        page.get_by_role('button', name='Назад').click()
        page.get_by_role('button', name='Пробный доступ · 10 поисков').click()
        assert page.locator('#profile-dropdown').is_hidden()
        assert page.locator('#oe').evaluate('(element) => element === document.activeElement')
        browser.close()
