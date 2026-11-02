"""Consumer data stays data: catalog generation needs only the standard library."""
import copy
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urljoin

import web_ui as ui


class Tags(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.tags = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class CatalogTests(unittest.TestCase):
    def spec(self):
        return ui.example_data('catalog-report')

    def test_both_examples_are_deterministic_and_do_not_mutate(self):
        for name in ('catalog-report', 'catalog-projects'):
            with self.subTest(name=name):
                spec = ui.example_data(name)
                before = copy.deepcopy(spec)
                page = ui.catalog_document(spec)
                self.assertEqual(page, ui.catalog_document(spec))
                self.assertEqual(spec, before)
                tags = Tags(page).tags
                self.assertEqual(sum(tag == 'h1' for tag, _ in tags), 1)
                self.assertEqual(sum(tag == 'article' for tag, _ in tags), 2)
                self.assertFalse(any(tag in ('script', 'link', 'img', 'iframe', 'base') for tag, _ in tags))

    def test_hostile_text_is_escaped_in_all_fields(self):
        hostile = '\"</style><script>alert(1)</script><img src=x> 日本語 🧪'
        spec = self.spec()
        spec.update(title=hostile, description=hostile)
        for item in spec['items']:
            item.update(title=hostile, summary=hostile, details=hostile, category=hostile)
            item['links'] = [{'label': hostile, 'href': './result.html?x=%22&y=1'}]
        page = ui.catalog_document(spec)
        self.assertNotIn(hostile, page)
        self.assertIn('&lt;script&gt;', page)
        self.assertFalse(any(tag in ('script', 'img') for tag, _ in Tags(page).tags))

    def test_ids_are_unique_prefixed_and_match_navigation(self):
        spec = self.spec()
        spec['items'][0]['id'] = 'top'
        tags = Tags(ui.catalog_document(spec)).tags
        ids = [attrs['id'] for _, attrs in tags if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('catalog-item-top', ids)
        for tag, attrs in tags:
            if tag == 'a' and attrs['href'].startswith('#'):
                self.assertIn(attrs['href'][1:], ids)
        spec['items'][1]['id'] = 'top'
        with self.assertRaises(ValueError):
            ui.catalog_document(spec)

    def test_bad_ids(self):
        for identity in ('', 'two words', '日本語', 'x" onclick="bad', '1bad', 'x' * 129, None, 1):
            with self.subTest(identity=identity):
                spec = self.spec()
                spec['items'][0]['id'] = identity
                with self.assertRaises(ValueError):
                    ui.catalog_document(spec)

    def test_rejects_unsafe_or_nonportable_links(self):
        for target in ('javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'java\nscript:alert(1)',
                       'data:text/html,bad', 'http://example.com', '//example.com', '/absolute',
                       '\\evil.test', 'https:\\evil.test', 'https:evil.test',
                       'https://@example.com', 'https://user:pass@example.com', 'https://example.com:bad',
                       'https://[broken', ' ./index.html', '', None):
            with self.subTest(target=target):
                spec = self.spec()
                spec['items'][0]['links'][0]['href'] = target
                with self.assertRaises(ValueError):
                    ui.catalog_document(spec)

    def test_relative_links_remain_relative_at_each_pages_subpath(self):
        spec = self.spec()
        expected = ['?q=foo:bar', './evidence/result.json?view=1#ok', '../guide.html', '#catalog-item-timing',
                    'https://example.com/reference?q=1&lang=ja']
        spec['items'][0]['links'] = [{'label': str(i), 'href': target} for i, target in enumerate(expected)]
        hrefs = [attrs['href'] for tag, attrs in Tags(ui.catalog_document(spec)).tags if tag == 'a']
        for target in expected:
            self.assertIn(target, hrefs)
        for base in ('https://owner.github.io/repo-a/', 'https://owner.github.io/repo-b/nested/'):
            self.assertEqual(urljoin(base, expected[1]), base + 'evidence/result.json?view=1#ok')

    def test_invalid_fields_types_and_limits(self):
        variants = [None, {}, {'schema': 'other', 'title': 'x', 'items': []}]
        for key, value in [('title', ''), ('title', 42), ('items', {}), ('description', '\x00'),
                           ('description', '\ud800'), ('items', [{}] * 513), ('unknown', True)]:
            spec = self.spec()
            spec[key] = value
            variants.append(spec)
        for change in ({'unknown': 1}, {'title': ''}, {'summary': []}, {'links': {}},
                       {'links': [{'label': 'x', 'href': './ok', 'target': '_blank'}]},
                       {'links': [{'label': '', 'href': './ok'}]}, {'details': 'x' * 16001}):
            spec = self.spec()
            spec['items'][0].update(change)
            variants.append(spec)
        for spec in variants:
            with self.subTest(spec=str(spec)[:100]):
                with self.assertRaises(ValueError):
                    ui.catalog_document(spec)

    def test_empty_catalog_and_all_themes(self):
        spec = {'schema': 'web-ui-catalog/1', 'title': 'Empty', 'items': []}
        for theme in ui.THEMES + ui.CANDIDATE_THEMES:
            self.assertIn(f'data-ui-theme="{theme}"', ui.catalog_document(spec, theme=theme))
        with self.assertRaises(ValueError):
            ui.catalog_document(spec, theme='unknown')

    def test_catalog_cli_utf8_under_legacy_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spec.json'
            for name in ('catalog-report', 'catalog-projects'):
                spec = ui.example_data(name)
                path.write_text(json.dumps(spec), encoding='utf-8')
                result = subprocess.run([sys.executable, '-S', ui.__file__, '--catalog', str(path)],
                                        env={**os.environ, 'PYTHONIOENCODING': 'cp1252'},
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.decode('utf-8'), ui.catalog_document(spec))

    def test_isolated_single_file_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'web_ui.py').write_bytes(Path(ui.__file__).read_bytes())
            (root / 'input.json').write_text(json.dumps(self.spec(), ensure_ascii=False), encoding='utf-8')
            done = subprocess.run([sys.executable, '-I', '-S', str(root / 'web_ui.py'),
                                   '--catalog', str(root / 'input.json')], capture_output=True, timeout=10)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.decode('utf-8'), ui.catalog_document(self.spec()))
            (root / 'input.json').write_text('{"invalid": true}', encoding='utf-8')
            bad = subprocess.run([sys.executable, '-I', '-S', str(root / 'web_ui.py'),
                                  '--catalog', str(root / 'input.json')], capture_output=True, timeout=10)
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(bad.stdout, b'')


if __name__ == '__main__':
    unittest.main()
