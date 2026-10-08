import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from web_ui import render_document, shared_stylesheets

ROOT = Path(__file__).resolve().parents[1]


class PythonWrapperTests(unittest.TestCase):
    def test_user_values_remain_text_and_no_scripts_are_added(self):
        html = render_document('<script>alert(1)</script>&', title='"<Title>')
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;&amp;', html)
        self.assertIn('&lt;Title&gt;', html)
        self.assertNotIn('<script', html)
        self.assertIn('data-ui-theme="modern"', html)

    def test_authored_html_and_css_can_be_supplied(self):
        html = render_document(trusted_html='<main class="ui-page">Hi</main>',
                               css='body { color: #000; background: #fff; }', theme='github-like')
        self.assertIn('<main class="ui-page">Hi</main>', html)
        self.assertIn('<style>body { color: #000; background: #fff; }</style>', html)
        self.assertIn('data-ui-theme="github-like"', html)

    def test_existing_assets_and_theme_order(self):
        links = shared_stylesheets('../vendor/web-ui', theme='github-like', stub=True)
        self.assertEqual(links[-2:], ('../vendor/web-ui/css/stub.css', '../vendor/web-ui/css/themes/github-like.css'))
        for href in shared_stylesheets('.'):
            self.assertTrue((ROOT / href).is_file())
        self.assertIn('href="a&amp;b.css"', render_document(stylesheets=('a&b.css',)))

    def test_invalid_inputs_and_raw_text_escape_are_rejected(self):
        for css in ('</STYLE><script>x</script>', '</style >', '</style/>'):
            with self.subTest(css=css), self.assertRaises(ValueError):
                render_document(css=css)
        for href in ('javascript:alert(1)', '//example.test/a.css', 'http://example.test/a.css', 'https://user:password@example.test/a.css'):
            with self.subTest(href=href), self.assertRaises(ValueError):
                render_document(stylesheets=(href,))
        with self.assertRaises(ValueError):
            render_document(theme='unknown')
        with self.assertRaises(ValueError):
            shared_stylesheets('https://example.test/main?ref=latest')

    def test_cli_stdlib_only_and_read_only_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            css = Path(directory) / 'palette.css'
            original = b'body { color: #000; }'
            css.write_bytes(original)
            run = subprocess.run([sys.executable, '-S', str(ROOT / 'web_ui.py'), '--css', str(css)],
                                 input='<b>user</b>', text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('&lt;b&gt;user&lt;/b&gt;', run.stdout)
            self.assertIn(original.decode(), run.stdout)
            self.assertEqual(css.read_bytes(), original)
        run = subprocess.run([sys.executable, '-S', str(ROOT / 'web_ui.py'), '--stub'],
                             input='', text=True, capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(run.stdout, '')


if __name__ == '__main__':
    unittest.main()
