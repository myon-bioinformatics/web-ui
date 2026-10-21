import json
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

import web_ui as ui


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ControlsTests(unittest.TestCase):
    def test_controls_escape_text_and_attributes(self):
        hostile = '\"><script>alert(1)</script>&'
        source = ui.button(hostile) + ui.select(((hostile, hostile),), id='choice', label=hostile)
        source += ui.input_field(id='text', label=hostile, value=hostile)
        source += ui.textarea(id='body', label=hostile, value='</textarea>' + hostile)
        source += ui.checkbox(hostile, id='flag') + ui.details(hostile, hostile)
        elements = Elements(source)
        self.assertNotIn('script', [tag for tag, _ in elements.tags])
        self.assertEqual([attrs['value'] for tag, attrs in elements.tags if tag == 'option'], [hostile])
        self.assertEqual([attrs['value'] for tag, attrs in elements.tags if tag == 'input' and attrs['type'] == 'text'], [hostile])
        labels = [attrs['for'] for tag, attrs in elements.tags if tag == 'label']
        self.assertEqual(labels, ['choice', 'text', 'body', 'flag'])
        self.assertIn('type="button"', source)

    def test_invalid_configurations_fail(self):
        for operation in (
            lambda: ui.button('x', type='onclick'), lambda: ui.input_field(id='x', label='x', type='file'),
            lambda: ui.select((('a', 'a'), ('a', 'b')), id='x', label='x'),
            lambda: ui.select((('a', 'a'),), id='x', label='x', selected='b'),
            lambda: ui.textarea(id='x', label='x', rows=0), lambda: ui.checkbox('x', id='x" onclick="x'),
        ):
            with self.assertRaises(ValueError): operation()

    def test_section_data_is_inert_and_duplicate_labels_have_distinct_values(self):
        body = '</script><script>danger()</script>&\u2028'
        source = ui.section_browser((('同名', body), ('同名', 'second')), full_text=body)
        elements = Elements(source)
        self.assertEqual(sum(tag == 'script' for tag, _ in elements.tags), 1)
        payload = source.split('data-ui-section-data>', 1)[1].split('</script>', 1)[0]
        self.assertNotIn('<', payload)
        data = json.loads(payload)
        self.assertEqual(data['fullText'], body)
        self.assertEqual([item['value'] for item in data['items']], ['0', '1'])
        self.assertEqual(data['items'][0]['body'], body)
        self.assertIn(' disabled', source)
        self.assertIn('controls.js', ui.shared_scripts('.', names=('controls.js',))[0])

    def test_stdlib_only_one_liner(self):
        code = 'from web_ui import *; print(render_document(trusted_html=section_browser((("概要", "本文"),), full_text="全文"), scripts=shared_scripts(".", names=("controls.js",))))'
        run = subprocess.run([sys.executable, '-S', '-c', code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('aria-live="polite"', run.stdout)
        self.assertIn('type="module" src="./js/controls.js"', run.stdout)

    def test_explicit_markdown_renderer_output_is_composable(self):
        self.assertIn('<table>', ui.details('Table', trusted_html='<table><tr><td>value</td></tr></table>'))
        self.assertNotIn('<table>', ui.details('Table', '<table>'))

    def test_badge_and_card_helpers(self):
        hostile = '\"><script>alert(1)</script>&'
        badge_html = ui.badge(hostile)
        self.assertEqual(badge_html, '<span class="ui-tag">&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;&amp;</span>')

        card_html = ui.card(hostile, title=hostile)
        self.assertIn('<article class="ui-card"><h2>&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;&amp;</h2>', card_html)
        self.assertIn('&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;&amp;</article>', card_html)

        trusted_card = ui.card(title='Card Title', trusted_html='<p>Trusted content</p>')
        self.assertEqual(trusted_card, '<article class="ui-card"><h2>Card Title</h2><p>Trusted content</p></article>')

    def test_sortable_table_helper(self):
        headers = ('Name', 'Age')
        rows = (('Alice', '30'), ('Bob', '25'))
        html = ui.sortable_table(headers, rows, id='my-table')

        self.assertIn('id="my-table"', html)
        self.assertIn('data-ui-sortable', html)
        self.assertIn('<button class="ui-button" type="button" data-ui-sort>Name</button>', html)
        self.assertIn('<td>Alice</td>', html)
        self.assertIn('<td>30</td>', html)

        with self.assertRaises(ValueError):
            ui.sortable_table((), ())

        with self.assertRaises(ValueError):
            ui.sortable_table(('Name', 'Age'), (('Alice',),))

    def test_key_value_list_and_alert_helpers(self):
        hostile = '\"><script>alert(1)</script>&'
        kv_html = ui.key_value_list({hostile: hostile})
        self.assertEqual(kv_html, '<dl class="ui-panel"><dt>&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;&amp;</dt><dd>&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;&amp;</dd></dl>')

        alert_html = ui.alert(hostile, title=hostile)
        self.assertIn('<section class="ui-panel"><h2>&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;&amp;</h2>', alert_html)
        self.assertIn('&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;&amp;</section>', alert_html)

        trusted_alert = ui.alert(title='Alert Title', trusted_html='<p>Trusted alert</p>')
        self.assertEqual(trusted_alert, '<section class="ui-panel"><h2>Alert Title</h2><p>Trusted alert</p></section>')
