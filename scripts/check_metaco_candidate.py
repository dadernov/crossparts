#!/usr/bin/env python3
"""Check a reviewed full METACO index and produce manual pilot examples."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from app.aggregator import Aggregator
from app.config import Settings
from app.excel import read_input
from app.normalize import number_key
from app.sources.registry import SourceRegistry


async def check(index: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, enabled_sources='',
        metaco_index_path=str(index.resolve()), browser_fallback=False,
        circular_search_enabled=False,
        pilot_rules=json.dumps({'metaco': {'groups': ['brake_pads', 'brake_discs'],
            'tenants': ['catalogue-review'], 'default': True}}))
    registry = SourceRegistry(settings)
    aggregator = Aggregator(settings, registry, None)
    cases = []
    fixtures = {}
    examples = []
    try:
        for path in sorted((ROOT / 'tests/fixtures/catalogues/metaco').glob('*/manifest.yaml')):
            manifest = yaml.safe_load(path.read_text())
            group = manifest['group']
            for filename, digest in manifest['fixtures'].items():
                assert hashlib.sha256((path.parent / filename).read_bytes()).hexdigest() == digest
                fixtures[f'{group}/{filename}'] = digest
            for case in manifest['cases']:
                result = await aggregator.lookup(case['query_raw'], ['metaco'],
                    group=group, tenant='catalogue-review')
                report = result['sources'][0]
                source = registry.get('metaco', group=group, tenant='catalogue-review')
                raw = await source.lookup(case['query_raw'])
                actual = {(c.brand, number_key(c.number), c.kind, c.source_product)
                          for c in raw.crosses}
                expected = {(c['brand_canonical'], str(c['number_key']), c['kind'], c['source_product'])
                            for c in case['expected_pairs']}
                assert result['status'] == case['expected_status'], case['case_id']
                assert report['products'] == case['expected_products'], case['case_id']
                assert actual == expected, case['case_id']
                merged_pairs = {(c['brand'], number_key(c['number']), product)
                                for c in result['crosses'] for product in c['source_products']}
                assert merged_pairs == {(b, n, p) for b, n, k, p in expected}, case['case_id']
                merged_kinds = {(c['brand'], number_key(c['number']), c['kind'], product)
                                for c in result['crosses'] for product in c['source_products']}
                kind_conflicts = len(expected - merged_kinds)
                forbidden = {(c['brand_canonical'], str(c['number_key']), c['kind'], c['source_product'])
                             for c in case['forbidden_pairs']}
                assert actual.isdisjoint(forbidden), case['case_id']
                cases.append({'case': case['case_id'], 'query': case['query_raw'],
                    'group': group, 'status': result['status'], 'evidence_rows': len(actual),
                    'unique_pairs': len(result['crosses']), 'products': report['products'],
                    'merged_kind_evidence_mismatches': kind_conflicts})
                if case['case_class'] == 'positive' and sum(e['group'] == group for e in examples) < 4:
                    examples.append(cases[-1])
        benchmark = []
        for group, query in [('brake_pads', '58101H5A25'), ('brake_discs', '1K0615301AA')]:
            samples = []
            for _ in range(200):
                start = time.perf_counter()
                result = await aggregator.lookup(query, ['metaco'], group=group, tenant='catalogue-review')
                samples.append((time.perf_counter() - start) * 1000)
            samples.sort()
            benchmark.append({'query': query, 'group': group, 'samples': len(samples),
                'p50_ms': statistics.median(samples), 'p95_ms': samples[189],
                'p99_ms': samples[197], 'max_ms': max(samples),
                'scope': 'registry + group-scoped adapter + merge; local full index, no shared cache',
                'unique_pairs': len(result['crosses']), 'external_requests': 0})
    finally:
        await registry.close()
    report = {'index_sha256': hashlib.sha256(index.read_bytes()).hexdigest(),
        'fixture_hashes': fixtures, 'passed_cases': len(cases), 'cases': cases,
        'precision': 1.0, 'recall': 1.0,
        'scope': 'Exact raw adapter evidence in 40 declared golden cases; merged brand/number/product pairs exact. Merged kind conflicts are reported separately, not counted as a pass.',
        'merged_kind_evidence_mismatches': sum(c['merged_kind_evidence_mismatches'] for c in cases),
        'benchmark': benchmark}
    (output / 'candidate-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Проверка METACO'
    sheet.append(['Наш артикул', 'Товарная группа', 'Номер ОЕ'])
    lines = ['# Номера для проверки METACO', '',
        'Кандидат выключен на production. Проверять в изолированном окружении с разрешённым pilot-account и выбранной группой. Другие бренды в ответе — кроссы METACO, а не новые подключения.', '',
        '| Группа | Номер для поиска | Ожидаемый артикул METACO |',
        '|---|---|---|']
    for i, example in enumerate(examples, 1):
        title = 'Тормозные колодки' if example['group'] == 'brake_pads' else 'Тормозные диски'
        sheet.append([f'TEST-{i:03}', title, str(example['query'])])
        sheet.cell(i + 1, 3).number_format = '@'
        lines.append(f"| {title} | `{example['query']}` | {', '.join(example['products'])} |")
    for cell in sheet[1]:
        cell.fill = PatternFill('solid', fgColor='263238')
        cell.font = Font(color='FFFFFF', bold=True)
    sheet.column_dimensions['A'].width = 20
    sheet.column_dimensions['B'].width = 28
    sheet.column_dimensions['C'].width = 25
    sheet.freeze_panes = 'A2'
    workbook.save(output / 'metaco-test.xlsx')
    parsed = read_input((output / 'metaco-test.xlsx').read_bytes())
    assert len(parsed) == len(examples)
    assert [(p['oe_number'], p['group']) for p in parsed] == [(e['query'], e['group']) for e in examples]
    (output / 'manual-check.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'passed_cases': len(cases), 'benchmark': benchmark,
                      'test_workbook': str(output / 'metaco-test.xlsx')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(check(args.index, args.output))
