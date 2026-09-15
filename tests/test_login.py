"""Authentication pages retain native password-manager form semantics."""
import asyncio

import httpx

from app import main


def test_login_form_and_native_redirect(monkeypatch):
    async def authenticate(_session, username, password):
        return username if (username, password) == ('form-check', 'test-password') else None

    monkeypatch.setattr(main, 'authenticate', authenticate)

    async def check():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url='https://test.local') as client:
            response = await client.get('/login')
            assert response.status_code == 200
            assert '<div id="entry-login">' in response.text
            assert 'action="/login" method="post" autocomplete="on"' in response.text
            assert 'name="username" autocomplete="username"' in response.text
            assert 'type="password" autocomplete="current-password"' in response.text
            response = await client.post('/login', data={'username': 'form-check', 'password': 'wrong-password'})
            assert response.status_code == 401
            assert 'Неверный логин или пароль' in response.text
            assert 'wrong-password' not in response.text
            assert '<div id="entry-login">' in response.text
            response = await client.post('/login', data={'username': 'form-check', 'password': 'test-password'})
            assert response.status_code == 303
            assert response.headers['location'] == '/'
            assert 'crossparts_session' in client.cookies
            response = await client.get('/')
            assert response.status_code == 200
            assert 'id="lookup-form"' in response.text
            assert 'id="login-form"' not in response.text
            assert 'test-password' not in response.text

    asyncio.run(check())
