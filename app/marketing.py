"""Public product pages: supported groups and enabled catalogue identities."""
from .groups import GROUPS

BRAND_ASSETS = {
    'kyb': ('KYB', 'kyb.png'),
    'sbparts': ('SB Nagamochi', 'sbparts.svg'),
    'brembo': ('Brembo', 'brembo.svg'),
    'trialli': ('TRIALLI', 'trialli.svg'),
    'brixo': ('Brixo', 'brixo.svg'),
    'luzar': ('LUZAR', 'luzar.svg'),
    'nissens': ('Nissens', 'nissens.svg'),
    'hola': ('HOLA', 'hola.svg'),
    'brannor': ('BRANNOR', 'brannor.svg'),
    'hel': ('HEL Performance', 'hel.png'),
    'metaco': ('METACO', 'metaco.svg'),
    'marshall': ('MARSHALL', 'marshall.svg'),
    'lynxauto': ('LYNXauto', 'lynxauto.svg'),
    'masterkit': ('MasterKit', 'masterkit.svg'),
    'fap': ('FAP', 'fap.svg'),
    'ganz': ('GANZ', 'ganz.svg'),
    'zimmermann': ('ZIMMERMANN', 'zimmermann.png'),
    'monaer': ('MONAER', 'monaer.png'),
    'ate': ('ATE', 'ate.png'),
    'febest': ('FEBEST', 'febest.svg'),
    'torr': ('TORR', 'torr.png'),
}
CATEGORY_COPY = {
    'brake_pads': ('Тормозные колодки', 'Аналоги дисковых тормозных колодок по оригинальному номеру. Для проверки позиции клиента и пополнения ассортимента.', '58101H5A25', 'pads'),
    'brake_discs': ('Тормозные диски', 'Поиск замен тормозных дисков в подключённых каталогах. Номера производителей и источники — в одном результате.', '1K0615301AA', 'discs'),
    'brake_hoses': ('Тормозные шланги', 'Подбор кросс-номеров тормозных шлангов по OE / OEM. Проверяйте исполнение и применимость по карточке производителя.', '1K0611701K', 'hoses'),
    'shock_absorbers': ('Амортизаторы', 'Поиск аналогов амортизаторов для работы с подвеской. Оригинальные номера и варианты замены из профильных каталогов.', '4851080378', 'shocks'),
    'radiators': ('Радиаторы охлаждения', 'Кросс-номера радиаторов системы охлаждения. Сопоставляйте предложения производителей и сохраняйте найденные номера.', '8200735038', 'radiators'),
}


def context(registry, settings, page='home'):
    sources = [s for s in registry.describe() if s['key'] in settings.default_sources]
    brands = [dict(key=s['key'], name=BRAND_ASSETS[s['key']][0],
                   image='/static/images/brands/' + BRAND_ASSETS[s['key']][1], url=s['homepage'])
              for s in sources if s['key'] in BRAND_ASSETS]
    categories = []
    for group in GROUPS:
        title, description, example, image = CATEGORY_COPY[group.key]
        categories.append(dict(key=group.key, title=title, description=description,
                               example=example, image=f"/static/images/categories/{image}.{'jpg' if image == 'pads' else 'png'}",
                               sources=[s['title'].split(' (')[0] for s in sources
                                        if not s['groups'] or group.key in s['groups']]))
    return dict(settings=settings, page=page, brands=brands, categories=categories)
