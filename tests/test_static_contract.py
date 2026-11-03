from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unittest
from posixpath import normpath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import web_ui  # noqa: E402

CONTRACT = ROOT / "contract" / "v1"
PAGES = web_ui.example_pages()  # the example pages are built in memory; there are no examples/*.html files


def _relative_luminance(hex_color):
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground, background):
    light, dark = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class ContractParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.icon_links = []
        self.classes = []
        self.ids = set()
        self.labels_for = set()
        self.stack = []
        self.class_parents = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and "icon" in values.get("rel", "").split():
            self.icon_links.append(values)
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if values.get("class"):
            self.classes.extend(values["class"].split())
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "label" and values.get("for"):
            self.labels_for.add(values["for"])


class StaticContractTest(unittest.TestCase):
    def parsed(self, path):
        return self.parsed_text(path.read_text(encoding="utf-8"))

    def parsed_text(self, text):
        parser = ContractParser()
        parser.feed(text)
        return parser

    def test_html_contract_v1_manifest_matches_fixture_and_css(self):
        manifest = json.loads((CONTRACT / "contract.json").read_text(encoding="utf-8"))
        fixture = PAGES["contract/v1/example.html"]
        css = web_ui.bundled_css()
        selectors = set(re.findall(r"\.(ui-[A-Za-z0-9_-]+|stub-[A-Za-z0-9_-]+)", css))

        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["status"], "stable")
        self.assertIn(
            f'data-ui-theme="{manifest["theme"]["default"]}"',
            fixture,
        )

        stable = (
            manifest["stable_classes"]["shared"]
            + manifest["stable_classes"]["stub"]
        )
        for class_name in stable:
            self.assertIn(class_name, fixture, f"fixture missing {class_name}")
            self.assertIn(class_name, selectors, f"CSS selector missing {class_name}")

    def test_html_contract_v1_declares_compatibility_boundary(self):
        manifest = json.loads((CONTRACT / "contract.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["extensions"]["removal_or_repurpose_requires"],
            "v2",
        )
        self.assertIn("exact colors", manifest["non_contract"])
        self.assertTrue(manifest["extensions"]["consumer_classes"])
        self.assertTrue(manifest["extensions"]["consumer_data_attributes"])
        self.assertEqual(manifest["version_policy"]["breaking_changes"], "require contract/v2")
        self.assertEqual(manifest["validation_scope"]["fixture_role"], "proof-of-presence, not a prescriptive layout template")

    def test_html_contract_v1_declared_themes_exist_and_use_theme_layer(self):
        manifest = json.loads((CONTRACT / "contract.json").read_text(encoding="utf-8"))
        for theme in manifest["theme"]["values"]:
            self.assertIn(f"themes/{theme}.css", web_ui._CSS, f"missing declared theme: {theme}")
            text = web_ui.css_source(f"themes/{theme}.css")
            self.assertIn("@layer theme", text, f"{theme} must stay in @layer theme")
            self.assertIn(f'data-ui-theme="{theme}"', text, f"{theme} selector must be scoped by data-ui-theme")

    def test_pages_entrypoints_resolve_the_repository_favicon(self):
        favicon = ROOT / "docs/brand/favicon.png"
        self.assertTrue(favicon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        for path in [ROOT / "index.html"]:
            with self.subTest(page=str(path.relative_to(ROOT))):
                links = self.parsed(path).icon_links
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0].get("type"), "image/png")
                href = links[0]["href"]
                self.assertFalse(urlsplit(href).scheme)
                self.assertFalse(href.startswith("/"))
                self.assertEqual((path.parent / href).resolve(), favicon.resolve())

    def test_pages_visible_and_touch_icons_resolve_to_canonical_asset(self):
        icon = ROOT / "docs/brand/icon.png"
        self.assertTrue(icon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        for path in [ROOT / "index.html"]:
            text = path.read_text(encoding="utf-8")
            patterns = [r'<link rel="apple-touch-icon" href="([^"]+)">']
            if path == ROOT / "index.html":
                patterns.append(r'<img[^>]+src="([^"]+)"')
            for pattern in patterns:
                href = re.search(pattern, text).group(1)
                self.assertFalse(urlsplit(href).scheme)
                self.assertEqual((path.parent / href).resolve(), icon.resolve())

    def test_example_pages_are_single_files_carrying_the_whole_bundle(self):
        self.assertEqual(sorted(PAGES), ["contract/v1/example.html", "examples/api-stub.html", "examples/clipboard-shelf.html", "examples/composition-studio.html", "examples/coordinates.html", "examples/door.html", "examples/github-like.html",
                                         "examples/index.html", "examples/mcp-lab.html", "examples/mcp-stub.html", "examples/photo-studio.html", "examples/play-studio.html", "examples/playground.html", "examples/showcase.html", "examples/test-report.html", "examples/timeline.html", "index.html"])
        self.assertEqual((ROOT / "index.html").read_text(encoding="utf-8"), PAGES["index.html"], "run: python -S web_ui.py --site DIR; copy DIR/index.html")
        for name, text in PAGES.items():
            self.assertNotIn('rel="stylesheet"', text, name)
            self.assertIn(web_ui.bundled_css(), text, name)
            self.assertNotIn("<script src", text, name)

    def test_theme_examples_keep_semantic_markup(self):
        text = PAGES["examples/github-like.html"]
        self.assertIn('data-ui-theme="github-like"', text)
        # Extend this list when an alternate-theme example intentionally demonstrates
        # additional semantic components; not every future ui-* class is mandatory.
        for class_name in ("ui-page", "ui-panel", "ui-card", "ui-button", "ui-input", "ui-tag", "ui-output"):
            self.assertIn(class_name, text)

    def test_github_like_muted_text_meets_wcag_aa(self):
        # Normal text requires at least 4.5:1 under WCAG AA.
        self.assertGreaterEqual(_contrast_ratio("#59636e", "#ffffff"), 4.5)

    def test_local_links_exist(self):
        for name, text in PAGES.items():
            for href in self.parsed_text(text).hrefs:
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc or href.startswith("#"):
                    continue
                target = normpath(str(Path(name).parent / parsed.path).replace("\\", "/"))
                self.assertIn(target, PAGES, f"{name}: broken href {href}")

    def test_ui_classes_follow_namespaces(self):
        for name, text in PAGES.items():
            for cls in self.parsed_text(text).classes:
                self.assertTrue(cls.startswith(("ui-", "stub-")), f"{name}: unnamespaced class {cls}")

    def test_labels_target_existing_controls(self):
        for name in ("examples/mcp-stub.html", "examples/api-stub.html"):
            parsed = self.parsed_text(PAGES[name])
            self.assertTrue(parsed.labels_for)
            self.assertTrue(parsed.labels_for <= parsed.ids)

    def test_stub_examples_share_tool_workspace_structure(self):
        required = ("stub-shell", "stub-header", "stub-toolbar", "stub-workspace", "stub-result", "stub-evidence", "stub-history", "stub-actions")
        for name in ("examples/mcp-stub.html", "examples/api-stub.html"):
            for class_name in required:
                self.assertIn(class_name, PAGES[name], f"{name}: missing {class_name}")

    def test_domain_protocols_not_in_generic_js(self):
        text = web_ui.EMBEDDED_STUB_JS.lower()
        for term in ("tools/list", "tools/call", "json-rpc", "authorization:"):
            self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()


def test_pages_root_is_one_self_contained_page_with_the_examples_inside():
    root = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'rel="stylesheet"' not in root and "<script src" not in root and 'src="./js/' not in root
    for anchor in ("#try", "#mcp", "#api", "#world", "#wall"):
        assert f'href="{anchor}"' in root and f'id="{anchor[1:]}"' in root, anchor


def test_output_surface_uses_neutral_high_contrast_palette():
    css = web_ui.css_source("components.css")
    assert ".ui-output" in css
    assert "background:#d8dee4" in css
    assert "color:#161b22" in css
    assert "pre.ui-output code{background:transparent}" in css


# --- Definition audit: CSS classes and custom properties may not pile up unnoticed. ---

def _css_sources():
    return sorted(web_ui._CSS)


def _css_text(name):
    return re.sub(r"/\*.*?\*/", "", web_ui.css_source(name), flags=re.S)


def test_every_css_class_is_referenced_by_markup_scripts_or_generators():
    # Declaration blocks are dropped first so values such as 1.5rem are not read as classes.
    defined = set()
    for path in _css_sources():
        defined |= set(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", re.sub(r"\{[^{}]*\}", "{}", _css_text(path))))
    # Classes the Python generators emit (tool/capture_matrix.py, tool/layout_presets.py) count as used.
    used_in = [*ROOT.glob("*.html"), ROOT / "web_ui.py", *(ROOT / "tool").glob("*.py")]
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in used_in) + "\n".join(PAGES.values()) + "\n".join(web_ui.js_modules().values())
    unused = sorted(name for name in defined
                    if not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", corpus))
    assert not unused, f"CSS classes nothing refers to: {unused}"


def test_css_variables_are_defined_generated_or_a_listed_gap():
    css = {name: _css_text(name) for name in _css_sources()}
    defined = {name for text in css.values() for name in re.findall(r"(--ui-[a-z0-9-]+)\s*:", text)}
    used = {name for text in css.values() for name in re.findall(r"var\((--ui-[a-z0-9-]+)", text)}
    # layout presets (tool/layout_presets.py) set these; matrix.css carries the defaults as fallbacks.
    generated = {"--ui-matrix-col", "--ui-matrix-gap", "--ui-matrix-pad"}
    # repository-diagnostics.css falls back to fixed colors; there is no token for them yet.
    known_gaps = {"--ui-surface", "--ui-text"}
    assert used - defined - generated <= known_gaps, sorted(used - defined - generated - known_gaps)
    # Defined but unused here or in any consumer checked on 2026-11-03; drop it after a deprecation window.
    dead_tokens = {"--ui-space"}
    tokens = set(re.findall(r"(--ui-[a-z0-9-]+)\s*:", css["tokens.css"]))
    assert tokens - used - dead_tokens == set(), sorted(tokens - used - dead_tokens)


def _theme_blocks():
    """Token values per theme: ``:root`` defaults, then each token-only block in tokens.css and each themes/ file."""
    tokens = _css_text("tokens.css")
    declared = lambda text: dict(re.findall(r"(--ui-[a-z0-9-]+)\s*:\s*([^;}]+)", text))
    root = declared(re.search(r":root\{([^}]*)\}", tokens).group(1))
    blocks = {"modern": {}}
    for theme, body in re.findall(r'body\[data-ui-theme="([a-z-]+)"\]\{([^}]*)\}', tokens):
        blocks[theme] = declared(body)
    for name in _css_sources():
        if name.startswith("themes/"):
            blocks.setdefault(name[len("themes/"):-len(".css")], {}).update(declared(_css_text(name)))
    return root, blocks


def test_themes_override_only_tokens_that_tokens_css_defines():
    # A new semantic token goes into :root with a default, so every theme has it.
    root, blocks = _theme_blocks()
    assert {"modern", "github-like", *web_ui.CANDIDATE_THEMES} <= set(blocks)
    for theme, values in blocks.items():
        assert set(values) <= set(root), f"{theme} invents tokens: {sorted(set(values) - set(root))}"


def test_text_tokens_meet_wcag_aa_in_every_theme():
    root, blocks = _theme_blocks()
    for theme, values in blocks.items():
        t = {**root, **values}
        for text, ground in [("fg", "bg"), ("fg", "panel"), ("muted", "bg"), ("muted", "panel"),
                             ("accent", "bg"), ("accent", "panel")]:
            ratio = _contrast_ratio(t[f"--ui-{text}"], t[f"--ui-{ground}"])
            assert ratio >= 4.5, f"{theme}: --ui-{text} on --ui-{ground} is {ratio:.2f}:1"
        # Non-text marks such as the fail outline need 3:1.
        for ground in ("bg", "panel"):
            assert _contrast_ratio(t["--ui-danger"], t[f"--ui-{ground}"]) >= 3, f"{theme}: --ui-danger on --ui-{ground}"
