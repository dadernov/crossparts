"""Browser regressions using real templates/assets and isolated API responses."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright


def test_frontend_states_and_layout():
    env = Environment(loader=FileSystemLoader('app/templates'), autoescape=True)
    attack = '<img src=x onerror="window.auditXss=1">'
    job = dict(id='test', filename=attack, status='failed', total=10, done=4,
               created_at='2026-09-09T12:00:00')
    response = dict(oe='58101H5A25', status='blocked', crosses=[], unique_numbers=[],
                    sources=[dict(source='brembo', status='blocked')])
    calls = {'lookup': 0, 'upload': 0}
    failures = {'jobs': False, 'lookup': False}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(r):
            path = r.request.url.split('http://audit.local')[-1]
            if path.startswith('/static/'):
                file = Path('app' + path.split('?', 1)[0])
                mime = {'.css': 'text/css', '.js': 'application/javascript', '.ttf': 'font/ttf'}[file.suffix]
                r.fulfill(body=file.read_bytes(), content_type=mime)
            elif path == '/api/v1/groups':
                r.fulfill(json={'groups': [{'title': 'Тормозные колодки', 'group': 'brake_pads'}]})
            elif path == '/api/v1/sources':
                r.fulfill(json={'sources': [dict(key='brembo', title='Brembo', groups=['brake_pads'])], 'default': ['brembo']})
            elif path.startswith('/api/v1/jobs?'):
                if failures['jobs']:
                    r.fulfill(status=500, body='<html>Internal error</html>')
                else:
                    r.fulfill(json=[job])
            elif path == '/api/v1/lookup':
                calls['lookup'] += 1
                if failures['lookup']:
                    r.fulfill(status=429, body='limit')
                else:
                    r.fulfill(json=response)
            elif path == '/api/v1/jobs/upload':
                calls['upload'] += 1
                r.fulfill(json={**job, 'status': 'pending'})
            elif path == '/api/v1/jobs/test':
                r.fulfill(json={'job': job, 'items': [dict(oe_number='123', part_name=attack, status='blocked', crosses_count=0)]})
            else:
                template = 'login.html' if path == '/login' else 'index.html'
                r.fulfill(body=env.get_template(template).render(username='demo', error=None), content_type='text/html')

        page.route('**/*', route)
        page.goto('http://audit.local/')
        page.wait_for_selector('.job-row')
        page.evaluate('document.fonts.ready')
        assert 'Ошибка задания' in page.locator('#jobs').inner_text()
        assert page.locator('#jobs img').count() == 0
        page.locator('#oe').fill('58101H5A25')
        page.locator('#btn-lookup').click()
        page.wait_for_function('!document.querySelector("#results").hidden')
        assert 'проверить не удалось' in page.locator('#result-summary').inner_text()
        failures['lookup'] = True
        page.locator('#btn-lookup').click()
        page.wait_for_function('document.querySelector("#lookup-status").textContent.includes("Слишком много")')
        assert not page.locator('#btn-lookup').is_disabled()
        failures['lookup'] = False
        response.update(status='ok', crosses=[dict(brand=attack, number='PN123', kind='aftermarket', sources=['brembo'], url='javascript:alert(1)')], unique_numbers=['PN123'])
        response['sources'] = [dict(source='brembo', status='ok')]
        page.locator('#btn-lookup').click()
        page.wait_for_selector('#result-rows code')
        assert page.locator('#result-rows img, #result-rows a').count() == 0
        assert not page.evaluate('Boolean(window.auditXss)')
        page.locator('#result-filter').fill('absent')
        assert 'По этому фильтру' in page.locator('#result-rows').inner_text()
        page.locator('#result-filter').fill('')
        page.get_by_role('button', name='Подробнее', exact=True).click()
        page.wait_for_selector('#detail-body table')
        assert 'Недоступен' in page.locator('#detail-body').inner_text()
        assert page.locator('#detail-body img').count() == 0
        page.locator('#close-details').click()
        page.locator('#file').set_input_files({'name': 'test.txt', 'mimeType': 'text/plain', 'buffer': b'test'})
        page.locator('#btn-upload').click()
        assert 'Нужен файл XLSX' in page.locator('#job-out').inner_text()
        assert calls['upload'] == 0
        page.locator('#file').set_input_files({'name': 'test.xlsx', 'mimeType': 'application/octet-stream', 'buffer': b'mocked'})
        page.evaluate('document.querySelector("#upload-form").requestSubmit(); document.querySelector("#upload-form").requestSubmit()')
        page.wait_for_function('document.querySelector("#job-out").textContent.includes("Задание создано")')
        assert calls['upload'] == 1
        failures['jobs'] = True
        page.locator('#refresh-jobs').click()
        page.wait_for_function('document.querySelector("#history-status").textContent.includes("неактуальна")')
        assert page.locator('#jobs .job-row').count() == 1
        failures['jobs'] = False
        # Ordinary safe data for design snapshots.
        response['crosses'] = [dict(brand='Brembo', number='P 30 122', kind='aftermarket', sources=['brembo'], url='https://www.bremboparts.com/'), dict(brand='HYUNDAI', number='58101-H5A25', kind='oem', sources=['brembo'])]
        response['unique_numbers'] = ['P30122', '58101H5A25']
        before = calls['lookup']
        page.evaluate('document.querySelector("#lookup-form").requestSubmit(); document.querySelector("#lookup-form").requestSubmit()')
        page.wait_for_function('document.querySelector("#result-rows").textContent.includes("HYUNDAI")')
        assert calls['lookup'] == before + 1
        job.update(filename='Колодки — сентябрь.xlsx', status='done', done=10)
        page.locator('#refresh-jobs').click()
        page.wait_for_selector('#jobs a')
        Path('out').mkdir(exist_ok=True)
        for width in [320, 375, 390, 768, 1440]:
            page.set_viewport_size({'width': width, 'height': 1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate('[...document.querySelectorAll("body *")].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>[e.tagName,e.id,e.className,e.getBoundingClientRect().right])')
            box = page.locator('#jobs a').bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            if width in [375, 1440]:
                page.screenshot(path=f'out/redesign-{width}.png', full_page=True)
        assert page.locator('#group').evaluate('(e)=>getComputedStyle(e).fontSize') == '16px'
        assert page.locator('#oe').evaluate('(e)=>e.labels.length') == 1
        assert page.evaluate('document.fonts.check("16px Golos")')
        page.goto('http://audit.local/login')
        page.locator('#show-password').check()
        assert page.locator('#password').get_attribute('type') == 'text'
        page.screenshot(path='out/redesign-login.png', full_page=True)
        assert not errors
        browser.close()
