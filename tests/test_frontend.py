"""Workspace v4 browser regressions; all API traffic is isolated from production."""
from pathlib import Path
import pytest
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from app.config import get_settings
from app.groups import GROUPS


@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_frontend_states_and_layout(browser_name):
    env = Environment(loader=FileSystemLoader('app/templates'), autoescape=True)
    attack = '<img src=x onerror="window.auditXss=1">'
    job = dict(id='test', filename='Колодки — сентябрь.xlsx', status='done', total=48, done=48,
               created_at='2026-09-15T12:00:00')
    cross = dict(brand='NiBK', number='PN0537', kind='aftermarket', sources=['brixo'])
    lookup = dict(oe='58101H5A25', status='ok', crosses=[cross], unique_numbers=['PN0537'],
                  sources=[dict(source='brixo', status='ok')])
    calls = {'lookup': 0, 'upload': 0, 'export': None, 'held': None, 'many_jobs': False}
    failures = {'lookup': False, 'jobs': False, 'hold': False}
    sources = [dict(key=key, title=title, homepage=url, groups=[]) for key, title, url in [
        ('sbparts', 'SB NAGAMOCHI', 'https://sbparts.ru'),
        ('brembo', 'Brembo', 'https://www.bremboparts.com/europe/ru'),
        ('trialli', 'TRIALLI', 'https://trialli.ru'),
        ('brixo', 'Brixo', 'https://brixogroup.com'), ('hola', 'HOLA', 'https://hola-auto.ru'),
        ('kyb', 'KYB', 'https://kyb.ru'), ('luzar', 'LUZAR', 'https://luzar.ru'),
        ('nissens', 'Nissens', 'https://catalogue.nissens.com'),
        ('brannor', 'BRANNOR', 'https://brannor.ru'), ('hel', 'HEL', 'https://helrussia.ru'),
    ]]
    with sync_playwright() as p:
        browser = getattr(p, browser_name).launch()
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))

        def route(r):
            path = r.request.url.split('http://audit.local')[-1]
            if path.startswith('/static/'):
                file = Path('app' + path.split('?', 1)[0])
                mime = {'.css':'text/css', '.js':'application/javascript', '.ttf':'font/ttf',
                        '.svg':'image/svg+xml', '.png':'image/png'}
                r.fulfill(body=file.read_bytes(), content_type=mime.get(file.suffix, 'application/octet-stream'))
            elif path == '/api/v1/groups':
                r.fulfill(json={'groups':[{'title':g.title,'group':g.key} for g in GROUPS]})
            elif path == '/api/v1/sources':
                r.fulfill(json={'sources':sources,'default':[s['key'] for s in sources]})
            elif path == '/api/v1/account':
                r.fulfill(json={'remaining':120,'limit':120})
            elif path.startswith('/api/v1/jobs?'):
                r.fulfill(status=500, body='error') if failures['jobs'] else r.fulfill(json=[{**job, 'id':str(i)} for i in range(min(int(path.split('limit=')[1]), 7))] if calls['many_jobs'] else [job])
            elif path == '/api/v1/jobs/test':
                r.fulfill(json={'job':job,'items':[dict(oe_number='58101H5A25', part_name='Колодки', status='ok', crosses_count=1)]})
            elif path == '/api/v1/jobs/test/results':
                r.fulfill(json={'rows':[{**cross, 'oe_number':'58101H5A25'}]})
            elif path == '/api/v1/lookup':
                calls['lookup'] += 1
                calls['payload'] = r.request.post_data_json
                if failures['hold']:
                    calls['held'] = r
                elif failures['lookup']:
                    r.fulfill(status=429, body='limit')
                else:
                    r.fulfill(json=lookup)
            elif path == '/api/v1/lookup/export.xlsx':
                calls['export'] = r.request.post_data_json
                r.fulfill(body=b'xlsx', content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            elif path == '/api/v1/jobs/upload':
                calls['upload'] += 1
                job.update(status='pending', done=0)
                r.fulfill(json=job)
            elif path == '/':
                r.fulfill(body=env.get_template('index.html').render(username='Алексей', is_trial=False,
                          settings=get_settings()), content_type='text/html')
            else:
                r.fulfill(status=404, body='not found')

        page.route('**/*', route)
        page.goto('http://audit.local/')
        page.wait_for_selector('#result-rows code')
        page.evaluate('document.fonts.ready')
        page.wait_for_function('document.querySelectorAll("#coverage img").length === 10 && [...document.querySelectorAll("#coverage img")].every(i => i.complete && i.naturalWidth > 0)')
        assert page.locator('#single-search').is_visible()
        assert page.locator('.result-variants, #variant2-rows').count() == 0
        assert page.locator('#result-table table').count() == 1
        assert page.locator('#coverage .catalog-card').count() == 10
        assert page.locator('.topbar a', has_text='Поддержка').get_attribute('href') == 'https://t.me/mrbdigital'
        assert page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(225, 229, 233)'
        for selector in ['h1','h2','.logo','button','input','th','code']:
            assert 'Onest' in page.locator(selector).first.evaluate('(e)=>getComputedStyle(e).fontFamily')
        assert page.locator('#profile-dropdown').is_hidden()
        page.locator('#profile-toggle').click()
        assert page.locator('#profile-dropdown').is_visible()
        assert page.locator('#profile-dropdown button').count() == 1
        assert page.locator('#profile-dropdown form').get_attribute('action') == '/logout'
        assert page.locator('#profile-dropdown form').get_attribute('method') == 'post'
        page.keyboard.press('Tab')
        assert page.get_by_role('button', name='Выйти', exact=True).evaluate('(e)=>e===document.activeElement')
        page.keyboard.press('Escape')
        assert page.locator('#profile-dropdown').is_hidden()
        assert page.locator('#profile-toggle').evaluate('(e)=>e===document.activeElement')
        page.keyboard.press('Enter')
        assert page.locator('#profile-dropdown').is_visible()
        page.locator('h1').click()
        assert page.locator('#profile-dropdown').is_hidden()
        assert page.locator('.results-panel').bounding_box()['y'] < page.locator('.history-panel').bounding_box()['y']
        assert page.locator('#job-export').get_attribute('href') == '/api/v1/jobs/test/export.xlsx'
        Path('output/workspace-site').mkdir(parents=True, exist_ok=True)
        for width in [320, 390, 768, 1024, 1440, 1920, 2560]:
            page.set_viewport_size({'width':width, 'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            if width in [390, 1440] and browser_name == 'chromium':
                page.screenshot(path=f'output/workspace-site/main-{width}.png', full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        search_box = page.locator('.combined-search').bounding_box()
        catalog_box = page.locator('.catalogues').bounding_box()
        assert search_box['y'] < catalog_box['y']
        assert abs(search_box['width'] - catalog_box['width']) < 2
        assert page.locator('.history-panel').bounding_box()['y'] < catalog_box['y']
        assert page.locator('#result-table th').first.evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(244, 245, 248)'
        # Choosing a file is an explicit picker, never an automatic upload.
        with page.expect_file_chooser():
            page.locator('#btn-upload').click()
        assert calls['upload'] == 0
        for group, number in [('brake_pads','58101H5A25'),('brake_discs','1K0615301AA'),
                              ('brake_hoses','1K0611701K'),('shock_absorbers','4851080378'),('radiators','8200735038')]:
            page.get_by_role('button', name=f'Подставить {number}', exact=True).click()
            assert page.locator('#oe').input_value() == number
            assert page.locator('#group').input_value() == group
        assert calls['lookup'] == 0
        page.get_by_role('button', name='Подставить 58101H5A25', exact=True).click()
        page.locator('#btn-lookup').click()
        page.wait_for_function('document.querySelector("#btn-export-lookup").hidden === false')
        assert page.locator('#result-rows .result-brand').first.inner_text() == 'NiBK'
        assert page.locator('#result-rows .result-brand img').count() == 0
        assert page.evaluate("normalizedBrand('VW')") == 'VOLKSWAGEN'
        assert page.evaluate("normalizedBrand('Volkswagen')") == 'VOLKSWAGEN'
        assert page.evaluate("normalizedBrand('CITROËN')") == 'CITROEN'
        assert page.evaluate("normalizedBrand('AUDI (FAW)')") == 'AUDI'
        assert page.evaluate("normalizedBrand('DAIMLER AG')") == 'MERCEDES BENZ'
        assert page.evaluate("normalizedBrand('VW (FAW)')") == 'VOLKSWAGEN'
        assert page.evaluate("normalizedBrand('VOLVO ASIA')") == 'VOLVO'
        assert page.evaluate("brandLogo('FEBI BILSTEIN').endsWith('/febi-bilstein.svg')")
        assert page.evaluate("brandLogo('LADA').endsWith('/lada.svg')")
        assert page.evaluate("brandLogo('SAKURA').endsWith('/sakura.png')")
        assert page.evaluate("brandLogo('DACIA').endsWith('/dacia.svg')")
        assert page.evaluate("brandLogo('ATE').endsWith('/ate.png')")
        assert page.evaluate("brandLogo('UNKNOWN BRAND')") is None
        assert page.evaluate("brandCell('OEM').innerText") == '—'
        assert page.evaluate("brandCell('UNKNOWN BRAND').querySelector('img') === null") is True
        assert page.evaluate("brandCell('UNKNOWN BRAND').querySelector('.brand-monogram') === null") is True
        assert page.evaluate("brandCell('UNKNOWN BRAND').innerText") == 'UNKNOWN BRAND'
        assert page.locator('#result-filter').bounding_box()['x'] < page.locator('#btn-export-lookup').bounding_box()['x']
        if browser_name == 'chromium':
            page.screenshot(path='output/workspace-site/lookup-controls.png')
        assert calls['payload'] == {'oe':'58101H5A25','group':'brake_pads'}
        assert page.locator('#result-table th').all_text_contents() == ['№', 'Номер OE / OEM', 'Бренд', 'Номер аналога', 'Источник']
        lookup['crosses'] = [{**cross, 'number':f'PN{i:04d}'} for i in range(25)]
        page.locator('#btn-lookup').click()
        page.wait_for_function('document.querySelector("#result-count").textContent === "25 номеров"')
        assert page.locator('#result-rows tr').count() == 12
        page.get_by_role('button', name='Страница 2', exact=True).click()
        assert page.locator('#result-rows td').first.inner_text() == '13'
        page.get_by_role('button', name='Следующая страница', exact=True).click()
        assert page.locator('#result-rows tr').count() == 1
        assert page.locator('#result-rows td').first.inner_text() == '25'
        page.locator('#result-filter').fill('PN0001')
        assert page.locator('#result-rows tr').count() == 1
        assert page.locator('#result-rows code').inner_text() == 'PN0001'
        page.locator('#result-filter').fill('')
        assert page.locator('#result-rows td').first.inner_text() == '1'
        lookup['crosses'] = [{**cross, 'number':f'PN{i:04d}'} for i in range(1200)]
        page.locator('#btn-lookup').click()
        page.wait_for_function('document.querySelector("#result-count").textContent === "1200 номеров"')
        page.get_by_role('button', name='Выбрать страницу', exact=True).first.click()
        assert page.locator('#page-number').evaluate('(e)=>e===document.activeElement')
        page.locator('#page-number').fill('57')
        page.locator('#page-number').press('Enter')
        assert page.locator('#result-rows td').first.inner_text() == '673'
        assert page.get_by_role('button', name='Страница 57', exact=True).get_attribute('aria-current') == 'page'
        page.locator('#page-number').fill('101')
        page.get_by_role('button', name='Перейти', exact=True).click()
        assert not page.locator('#page-number').evaluate('(e)=>e.validity.valid')
        assert page.locator('#result-rows td').first.inner_text() == '673'
        page.locator('#page-number').fill('100')
        page.get_by_role('button', name='Перейти', exact=True).click()
        assert page.locator('#result-rows td').first.inner_text() == '1189'
        assert page.get_by_role('button', name='Следующая страница', exact=True).is_disabled()
        page.set_viewport_size({'width':320,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':1440,'height':1000})
        page.locator('#result-filter').fill('PN0001')
        assert page.locator('#result-pages button').count() == 0
        page.locator('#result-filter').fill('')
        assert page.locator('#page-number').input_value() == '1'
        # Export must retain the submitted category even after the form changes.
        page.get_by_role('button', name='Подставить 8200735038', exact=True).click()
        with page.expect_download():
            page.locator('#btn-export-lookup').click()
        assert calls['export']['group'] == 'brake_pads'
        def choose_format(selector, value):
            picker = page.locator(selector).locator('xpath=following-sibling::div[1]')
            picker.locator('.format-trigger').click()
            picker.locator(f'[data-value="{value}"]').click()
            assert picker.locator('.format-options').is_hidden()
        picker = page.locator('#export-format').locator('xpath=following-sibling::div[1]')
        picker.locator('.format-trigger').focus()
        page.keyboard.press('ArrowDown')
        assert picker.locator('.format-options').is_visible()
        page.keyboard.press('End')
        page.keyboard.press('Enter')
        assert page.locator('#export-format').input_value() == 'json'
        picker.locator('.format-trigger').click()
        page.keyboard.press('Escape')
        assert picker.locator('.format-options').is_hidden()
        assert page.locator('#result-rows tr').nth(1).evaluate('(e)=>getComputedStyle(e).backgroundColor') == 'rgb(231, 235, 240)'
        # All rows export, including those outside the current page/filter.
        import json
        choose_format('#export-format', 'json')
        with page.expect_download() as info:
            page.locator('#btn-export-lookup').click()
        exported = json.loads(Path(info.value.path()).read_text())
        assert len(exported) == 1200
        assert exported[0]['oe_number'] == '58101H5A25'
        choose_format('#export-format', 'csv')
        with page.expect_download() as info:
            page.locator('#btn-export-lookup').click()
        csv = Path(info.value.path()).read_text(encoding='utf-8-sig')
        assert 'Номер OE / OEM' in csv and 'PN1199' in csv
        choose_format('.job-actions select', 'json')
        with page.expect_download() as info:
            page.locator('.job-actions a').click()
        assert json.loads(Path(info.value.path()).read_text())[0]['number'] == 'PN0537'
        choose_format('#export-format', 'xlsx')
        page.locator('#result-filter').fill('nothing matches')
        assert 'По этому фильтру' in page.locator('#result-rows').inner_text()
        page.locator('#result-filter').fill('')
        failures['lookup'] = True
        page.locator('#btn-lookup').click()
        page.wait_for_function('document.querySelector("#lookup-status").textContent.includes("Слишком много")')
        assert not page.locator('#btn-lookup').is_disabled()
        failures['lookup'] = False
        lookup.update(status='blocked', crosses=[], unique_numbers=[], sources=[dict(source='brixo',status='blocked')])
        page.locator('#btn-lookup').click()
        page.wait_for_function('document.querySelector("#result-summary").textContent.includes("проверить не удалось")')
        assert page.locator('#source-details').get_attribute('open') is not None
        assert page.locator('#btn-export-lookup').is_hidden()
        lookup.update(status='ok', crosses=[{**cross,'brand':attack}], unique_numbers=['PN0537'], sources=[dict(source='brixo',status='ok')])
        page.locator('#btn-lookup').click()
        page.wait_for_selector('#result-rows code')
        assert page.locator('#result-rows img').count() == 0
        assert not page.evaluate('Boolean(window.auditXss)')
        # A delayed lookup must not replace the job opened afterward.
        failures['hold'] = True
        page.locator('#btn-lookup').click()
        page.wait_for_timeout(100)
        assert calls['held'] is not None
        page.get_by_role('button', name='Открыть', exact=True).click()
        page.wait_for_function('document.querySelector("#result-query").textContent.includes("сентябрь")')
        calls['held'].fulfill(json=lookup)
        page.wait_for_function('!document.querySelector("#btn-lookup").disabled')
        assert 'сентябрь' in page.locator('#result-query').inner_text()
        failures['hold'] = False
        assert page.locator('#single-search').is_visible()
        # Safe rendering, validation, duplicate upload guard and job polling.
        job['filename'] = attack
        page.locator('#refresh-jobs').click()
        page.wait_for_function('document.querySelector("#jobs").textContent.includes("onerror")')
        assert page.locator('#jobs img').count() == 0
        page.locator('#file').set_input_files({'name':'bad.txt','mimeType':'text/plain','buffer':b'test'})
        page.locator('#btn-upload').click()
        assert 'Нужен файл XLSX' in page.locator('#job-out').inner_text()
        assert calls['upload'] == 0
        page.locator('#file').set_input_files({'name':'test.xlsx','mimeType':'application/octet-stream','buffer':b'mocked'})
        page.evaluate('document.querySelector("#upload-form").requestSubmit(); document.querySelector("#upload-form").requestSubmit()')
        page.wait_for_function('document.querySelector("#job-out").textContent.includes("Задание создано")')
        page.wait_for_function('document.querySelector("#result-summary").textContent.includes("В очереди")')
        assert calls['upload'] == 1
        assert page.locator('#job-export').is_hidden()
        job.update(status='done',done=48)
        page.locator('#refresh-jobs').click()
        page.wait_for_function('!document.querySelector("#job-export").hidden')
        assert page.locator('#job-export').is_visible()
        calls['many_jobs'] = True
        page.locator('#refresh-jobs').click()
        page.wait_for_function('document.querySelectorAll(".job-row").length === 2')
        page.locator('#more-jobs').click()
        page.wait_for_function('document.querySelectorAll(".job-row").length === 7')
        page.locator('#collapse-jobs').click()
        page.wait_for_function('document.querySelectorAll(".job-row").length === 2')
        calls['many_jobs'] = False
        page.locator('#refresh-jobs').click()
        page.wait_for_function('document.querySelectorAll(".job-row").length === 1')
        failures['jobs'] = True
        page.locator('#refresh-jobs').click()
        page.wait_for_function('document.querySelector("#history-status").textContent.includes("неактуальна")')
        assert page.locator('.job-row').count() == 1
        assert not errors
        browser.close()
