"""Regression cases for the inventory's heuristic, not a Dart equivalence checker."""
import importlib.util
from pathlib import Path
import unittest

_spec = importlib.util.spec_from_file_location(
    'flutter_inventory', Path(__file__).resolve().parents[1] / 'tool/flutter_migration_inventory.py')
_inventory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_inventory)
shape = _inventory._shape


class DartShapeTests(unittest.TestCase):
    def test_plain_quoting_styles(self):
        sources = ["var x = 'hello';", 'var x = "world";',
                   "var x = '''first\nsecond''';", 'var x = """first\nsecond""";']
        self.assertEqual(len({shape(source) for source in sources}), 1)

    def test_escaped_quotes_and_backslashes(self):
        for literal in [r"'it\'s'", r'"quote\" and \\"', r"'''a\'''b'''", r'"""a\"""b"""']:
            with self.subTest(literal=literal):
                self.assertEqual(shape('var x = ' + literal + ';'), shape("var x = 'plain';"))

    def test_raw_strings_have_no_interpolation_or_escapes(self):
        for literal in [r"r'$thing\'", r'r"${call()}\"', "r'''a\n$b'''", 'r"""${x}\ny"""']:
            with self.subTest(literal=literal):
                self.assertEqual(shape('var x = ' + literal + ';'), shape("var x = 'plain';"))

    def test_comment_forms(self):
        base = 'var x = 1; var y = 2;'
        variants = ['// intro\n' + base, 'var x = 1; // trailing\nvar y = 2;',
                    'var /* outer /* nested */ done */ x = 1; var y = 2;',
                    'var x = 1; /* multiline\ncomment */ var y = 2;']
        for source in variants:
            self.assertEqual(shape(base), shape(source))

    def test_comment_markers_inside_strings(self):
        for literal in ["'https://a/*b*/'", '"// not comment"', "'''first\n//not comment\n/* still string */'''", '"""first\n//not comment\n"""']:
            self.assertEqual(shape('var x = ' + literal + '; next();'), shape("var x = 'label'; next();"))

    def test_interpolation_labels_are_ignored_but_expressions_remain(self):
        self.assertEqual(shape("'Pattern1: $message'"), shape('"Pattern2: ${message}"'))
        self.assertNotEqual(shape("'$message'"), shape("'$other'"))
        self.assertNotEqual(shape("'${a + b}'"), shape("'${a - b}'"))
        self.assertNotEqual(shape("'$message'"), shape("'message'"))

    def test_nested_interpolation_strings_braces_and_comments(self):
        self.assertEqual(shape('"${render("}", {\'key\': item}) /* } */}"'),
                         shape("'''${render('label', {'label': item})}'''"))
        self.assertNotEqual(shape('"${render("${first}")}"'), shape('"${render("${second}")}"'))

    def test_interpolation_order_and_multiplicity(self):
        self.assertNotEqual(shape("'$a $b'"), shape("'$b $a'"))
        self.assertNotEqual(shape("'$a $a'"), shape("'$a'"))

    def test_comments_do_not_join_tokens(self):
        self.assertEqual(shape('foo/**/bar'), shape('foo bar'))
        self.assertNotEqual(shape('foo/**/bar'), shape('foobar'))
        self.assertNotEqual(shape('a + /* gap */ + b'), shape('a ++ b'))

    def test_template_normalization_is_deliberately_not_equivalence(self):
        self.assertEqual(shape('Pattern1Result(12)'), shape('Pattern2Result(34)'))
        self.assertEqual(shape("'${value + 1}'"), shape("'${value + 2}'"))
        self.assertNotEqual(shape('sha256(value)'), shape('sha512(value)'))
        self.assertNotEqual(shape('fooPattern12(value)'), shape('fooPattern34(value)'))
        self.assertNotEqual(shape('value + N'), shape('value + 1'))

    def test_unterminated_constructs_fail(self):
        for source in ["'unterminated", '"unterminated', "'''unterminated", '/* unfinished', '"${call()"']:
            with self.subTest(source=source), self.assertRaises(ValueError):
                shape(source)


if __name__ == '__main__':
    unittest.main()
