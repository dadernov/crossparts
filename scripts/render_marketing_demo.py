"""Render an isolated UI example; never calls production APIs or uses customer data."""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from app.main import registry, settings


def render():
    env = Environment(loader=FileSystemLoader('app/templates'), autoescape=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1440,'height':1000}, device_scale_factor=1)
        def route(r):
            path = r.request.url.split('http://demo.local')[-1].split('?')[0]
            if path.startswith('/static/'):
                file=Path('app'+path)
                mime={'.css':'text/css','.js':'application/javascript','.ttf':'font/ttf','.svg':'image/svg+xml','.png':'image/png'}
                r.fulfill(body=file.read_bytes(),content_type=mime.get(file.suffix,'application/octet-stream'))
            elif path=='/api/v1/groups':r.fulfill(json={'groups':registry.coverage()})
            elif path=='/api/v1/sources':r.fulfill(json={'sources':registry.describe(),'default':settings.default_sources})
            elif path=='/api/v1/account':r.fulfill(json={'remaining':10,'limit':10})
            elif path=='/api/v1/jobs':r.fulfill(json=[])
            elif path=='/api/v1/lookup':
                # Pair recorded in tests/fixtures/brixo_info_PN0537.json.
                r.fulfill(json={'oe':'58101H5A25','status':'ok','crosses':[{'brand':'NiBK','number':'PN0537','kind':'aftermarket','sources':['brixo'],'url':'https://brixogroup.com/catalog'}],'unique_numbers':['PN0537'],'sources':[{'source':'brixo','status':'ok'}]})
            elif path=='/':r.fulfill(body=env.get_template('index.html').render(settings=settings,username='Демо',is_trial=True),content_type='text/html')
            else:r.fulfill(status=404)
        page.route('**/*',route)
        page.goto('http://demo.local/')
        page.wait_for_selector('.group-example', state='attached')
        page.evaluate('document.fonts.ready')
        page.locator('#oe').fill('58101H5A25')
        page.locator('#btn-lookup').click()
        page.wait_for_selector('#result-rows code')
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path='app/static/images/demo-workspace.png')
        browser.close()
if __name__=='__main__':render()
