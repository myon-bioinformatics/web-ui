"""Read-only, stdlib inventory of a flutter_navigation_basic checkout, with what web-ui did about each file. No network; no archive action.

    python -S tool/flutter_migration_inventory.py /path/to/flutter_navigation_basic --output docs/flutter-migration-inventory.json
    python -S tool/flutter_migration_inventory.py /path/to/flutter_navigation_basic --output docs/flutter-migration-inventory.json --check

``--check`` rebuilds the inventory and exits 1 if the file on disk differs (it writes nothing).

A status says what web-ui did, not that the original was reviewed line by line:

* ``successor``: web-ui has an implementation with tests whose golden values come from the original (or, for Flutter widgets, a page that does the same job);
* ``partial``: a successor exists but ``remaining`` names what is deliberately not carried over;
* ``not_absorbed``: web-ui decided not to take it, and ``remaining`` says why;
* ``pending``: asked for, not done yet;
* ``proposed_retirement``: Flutter runtime that has no counterpart on the web; retiring it needs the owner's approval;
* ``unreviewed``: nobody has decided.

``archive_ready`` stays false while anything is ``pending`` or ``unreviewed``, or a retirement is not approved.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY = 'myon-bioinformatics/flutter_navigation_basic'

# feature directory (lib/features/NAME) -> status, target, remaining. A path rule below wins over a feature rule.
TARGETS = {
    'photo_studio': ('partial', 'PhotoStudio, photo_document', 'Native camera, clipboard, share and HEIC stay platform-specific'),
    'composition_generator': ('partial', 'studio_document, progression_notes, studio_audio_plan', 'Audio is opt-in; the seeded generator differs from Dart Random on purpose'),
    'now_timeline': ('partial', 'timeline_events, timeline_wall_to_utc, world_document', 'Recurrence, stored entries, notifications and booking are not migrated'),
    'counter_playground': ('successor', 'counter_garden, play_document', 'New reward model; native hold-repeat timing is not copied'),
    'irony_generator': ('successor', 'irony_round, play_document', 'New authored quiz deck; the original text corpus stays at the source'),
    'coordinate_tool': ('partial', 'coordinates_document', 'Network short-link expansion is excluded on purpose'),
    'clipboard_shelf': ('partial', 'shelf_document', 'Native clipboard platform behaviour is not equivalent'),
    'http_request_draft': ('partial', 'parse_curl, stub_document', 'External HTTP execution is not absorbed; local fixture authentication is available via MockAuthHandler (web-ui sends nothing)'),
    'screen5': ('partial', 'screen_view (screen 5 as its generic screen, with a note)', "The URL-parameter tool's dedicated GetX controller is not absorbed"),
    'home': ('partial', 'door_document, page identities', 'Home cards are Flutter widgets; the Door selector and page identities are the web-ui pages'),
}

RETIRE = 'Flutter runtime with no counterpart on the web (routes, bootstrap, GetX services, platform shims, theme constants, widgets)'

# Longest matching prefix wins. (prefix, status, target, remaining)
PATH_RULES = (
    ('lib/screens/generic_screen.dart', 'successor', 'screen_view, screen_step', 'Widgets are semantic HTML; data and texts are embedded in the page'),
    ('lib/screens/pattern_template_screen.dart', 'successor', 'screen_template, screen_template_view (eleven templates)', ''),
    ('lib/screens/hub_screen.dart', 'successor', 'screen_hub', ''),
    ('lib/shared/catalog/', 'successor', 'screen_search, pattern_find', ''),
    ('lib/shared/display/', 'successor', 'screen_text (11 locales, 59 keys, golden against assets/display/app_text.json)', ''),
    ('lib/core/data_processing/native_', 'successor', 'native_initial, native_step, native_view, native_parallel (patterns 136-137, 151-170)', 'Counts notifications and rebuilds; pattern 136-137 uses a Web Worker where Dart uses an Isolate'),
    ('lib/core/data_processing/counter_architecture_example.dart', 'successor', 'native_* (patterns 166-170)', ''),
    ('lib/core/data_processing/state_architecture_example.dart', 'successor', 'native_* (patterns 166-170)', ''),
    ('lib/core/data_processing/inherited_catalogue_example.dart', 'successor', 'native_* (patterns 151-165)', ''),
    ('lib/core/data_processing/interactive_pattern_example.dart', 'successor', 'native_* gestures (patterns 171-175, 183-184)', 'The original exposes it in E2E builds only'),
    ('lib/core/data_processing/', 'successor', 'screen_links_view, pattern_run (the display boundary of lists processed in Python)', ''),
    ('lib/screens/mcp_integration_screen.dart', 'successor', 'mcp_document', 'PR #109'),
    ('lib/shared/mcp/', 'successor', 'mcp_* (MCP lab)', 'PR #109; ids and verifiers come from an injected random source'),
    ('lib/screens/ui_showcase_screen.dart', 'successor', 'showcase_document', ''),
    ('lib/data/composer.dart', 'partial', 'progression_notes, studio_document, song_seed', 'The seeded generator differs from Dart Random on purpose'),
    ('lib/data/ironies.dart', 'successor', 'irony_round, play_document', 'New authored quiz deck; the original text corpus stays at the source'),
    ('lib/shared/http/auth_matrix.dart', 'partial', 'auth_matrix, auth_prepare, auth_document (/auth.html)', 'All eleven local presets; RequestDraft sensitive-field metadata and Flutter draft UI are not migrated'),
    ('lib/shared/http/digest_nc.dart', 'successor', 'digest_nc_parse, digest_nc_format', ''),
    ('lib/shared/http/mock_auth.dart', 'successor', 'MockAuthHandler, auth_digest_response, auth_hmac_signature, auth_query_pairs', 'Local fixture router only; /mock-auth accepts simulated requests; no external authentication'),
    ('lib/shared/http/live_request_executor', 'not_absorbed', None, 'Sends real HTTP requests; web-ui tools send nothing'),
    ('lib/shared/http/request_executor.dart', 'not_absorbed', None, 'Sends real HTTP requests; web-ui tools send nothing'),
    ('lib/shared/http/curl_runtime_transport', 'not_absorbed', None, 'Sends real HTTP requests; web-ui tools send nothing'),
    ('lib/shared/http/', 'partial', 'parse_curl, mask_curl, stub_document', "The editor's subset of curl; nothing is executed"),
    ('lib/screens/clipboard_shelf_screen.dart', 'partial', 'shelf_document', 'Native clipboard platform behaviour is not equivalent'),
    ('lib/shared/clipboard/', 'partial', 'photo_document, shelf_document', 'Native clipboard platform behaviour is not equivalent'),
    ('lib/shared/widgets/clipboard_', 'partial', 'shelf_document', 'Native clipboard platform behaviour is not equivalent'),
    ('lib/shared/widgets/session_text_clipboard.dart', 'partial', 'shelf_document', 'Native clipboard platform behaviour is not equivalent'),
    ('lib/shared/widgets/chord_theory_card.dart', 'partial', 'progression_notes, studio_document', ''),
    ('lib/shared/widgets/composition_studio.dart', 'partial', 'studio_document, studio_audio_plan', ''),
    ('lib/shared/widgets/note_sequence_card.dart', 'partial', 'progression_notes', ''),
    ('lib/shared/widgets/song_seed_panel.dart', 'partial', 'song_seed, studio_document', ''),
    ('lib/shared/widgets/hold_repeating_button.dart', 'successor', 'counter_garden, hold_repeat_count, play_document', 'Native hold-repeat timing is not copied'),
    ('lib/shared/widgets/tool_door_selector.dart', 'successor', 'door_document', ''),
    ('lib/shared/widgets/home_overview_panel.dart', 'partial', 'door_document', 'Home cards are Flutter widgets'),
    ('lib/shared/navigation/page_identities.g.dart', 'successor', 'page identities (door_document)', 'Generated by python/generate_page_identities.py, which web-ui absorbed'),
    ('lib/core/navigation/app_tools.dart', 'partial', 'door_document', 'One route/label identity for Home and the Door footer'),
    ('lib/screens/', 'partial', 'the successor page of the same tool (see the feature rows)', 'Flutter screen widget'),
    ('lib/shared/widgets/standard_page_', 'proposed_retirement', None, 'Flutter page chrome; web-ui pages have their own'),
    ('lib/shared/widgets/', 'proposed_retirement', None, RETIRE),
    ('lib/shared/themes/', 'proposed_retirement', None, 'Flutter theme constants; web-ui themes are token files'),
    ('lib/shared/diagnostics/', 'proposed_retirement', None, 'Flutter build diagnostics overlay, route observer and weight badge'),
    ('lib/shared/bootstrap/', 'proposed_retirement', None, RETIRE),
    ('lib/shared/platform/', 'proposed_retirement', None, RETIRE),
    ('lib/core/navigation/', 'proposed_retirement', None, 'GetX route table and registry'),
    ('lib/core/exceptions/', 'proposed_retirement', None, RETIRE),
    ('lib/core/logging/', 'proposed_retirement', None, RETIRE),
    ('lib/core/services/', 'proposed_retirement', None, RETIRE),
    ('lib/core/config/', 'proposed_retirement', None, RETIRE),
    ('lib/config', 'proposed_retirement', None, RETIRE),
    ('lib/data/mock_api_client.dart', 'proposed_retirement', None, 'GetConnect client of the Flutter app'),
    ('lib/main.dart', 'proposed_retirement', None, RETIRE),
    ('lib/widgets/', 'proposed_retirement', None, RETIRE),
)

# python/ tools, build_tools, ci, e2e and the workflows: name -> status, target, remaining
PYTHON_TOOLS = {
    'collection_query_patterns.py': ('successor', 'pattern_run("query")', 'Golden: tests/fixtures/pattern_golden.json'),
    'search_patterns.py': ('successor', 'pattern_run("search")', ''),
    'pagination_patterns.py': ('successor', 'pattern_run("page")', ''),
    'scoring_heap_patterns.py': ('successor', 'pattern_run("score")', ''),
    'state_reducer.py': ('successor', 'pattern_run("reduce")', ''),
    'conversion_patterns.py': ('successor', 'pattern_run("convert")', ''),
    'validation_patterns.py': ('successor', 'pattern_run("validate")', ''),
    'workflow_patterns.py': ('successor', 'pattern_run("workflow")', ''),
    'collection_transform.py': ('successor', 'pattern_run("transform")', ''),
    'list_selection.py': ('successor', 'pattern_run("select")', ''),
    'list_ordering.py': ('successor', 'pattern_run("order")', ''),
    'text_processing.py': ('successor', 'pattern_run("text")', ''),
    'collection_window.py': ('successor', 'pattern_run("window")', ''),
    'collection_structure.py': ('successor', 'pattern_run("structure")', ''),
    'pattern_responsibility_audit.py': ('successor', 'pattern_owner', "The audit's rules, copied"),
    'metadata_contracts.py': ('successor', 'pattern_run("contract") (operations screens and locales)', 'Golden: tests/fixtures/contract_golden.json (the original run on seeded mutations)'),
    'header_contracts.py': ('successor', 'pattern_run("contract") operation layout', 'The header title-emoji identity belongs to Flutter and is left out'),
    'gesture_paint.py': ('successor', 'pattern_run("contract") operation swap', 'PNGs are decoded by studio_png_decode'),
    'image_diff.py': ('successor', 'pattern_run("contract") operation swap', 'Exact RGBA comparison'),
    'validation_http.py': ('successor', 'python3 web_ui.py --pattern-serve', 'A loopback bridge for every family, with the same Host/Origin/size/media-type rules'),
    'curl_request.py': ('successor', 'parse_curl, mask_curl', 'Golden: tests/fixtures/curl_request_cases.json'),
    'curl_runtime_server.py': ('not_absorbed', None, 'Executes real HTTP requests; web-ui tools send nothing'),
    'outcomes.py': ('successor', 'junit_report, flutter_outcomes', ''),
    'flutter_machine_junit.py': ('successor', 'flutter_machine_junit', ''),
    'validate_runner_junit.py': ('successor', 'junit_inspect', ''),
    'junit_history.py': ('successor', 'junit_history, junit_diff', ''),
    'failure_identity.py': ('successor', 'junit_failure_records', ''),
    'multi_test_runner.py': ('successor', 'run_test_suite, runner_command', ''),
    'node_test_runner.py': ('successor', 'run_test_suite (runner playwright-node, deno)', ''),
    'expected_child_failure.py': ('successor', 'expected_child_failure', ''),
    'generate_page_identities.py': ('successor', 'page identities (door_document)', ''),
    'home_discovery.py': ('successor', 'door_document', ''),
    'generate_zone_table.py': ('successor', 'zone_rows, zone_offset', 'The scan and bisection are followed'),
    'oracle_selection.py': ('proposed_retirement', None, 'A CI job-ownership rule: selects the Python fallback only when the Non-Dart job does not own the full pytest run; web-ui runs its suites whole'),
    'dart_contracts.py': ('proposed_retirement', None, 'Executes production Dart contracts with the Dart SDK and checks the output in Python; the Dart sources are not carried over'),
    'generate_pattern_contracts.py': ('proposed_retirement', None, 'Generates the single Dart producer that replaced 594 duplicated Flutter test suites'),
    'pattern_contracts.py': ('proposed_retirement', None, 'Validates real Dart output (per-case JUnit failures)'),
    'generate_pattern_smoke_test.py': ('proposed_retirement', None, 'Generates the Flutter catalogue smoke test'),
    'check_pattern_smoke_mutations.py': ('proposed_retirement', None, 'Proves the generated Flutter suite rejects thrown or empty production services'),
    'pattern_stub_audit.py': ('proposed_retirement', None, 'Audits generated Dart pattern services for placeholder implementations'),
    'render_pattern_status.py': ('proposed_retirement', None, 'Renders the 198 evidence-based catalogue statuses of the Dart app as Markdown'),
    'capture_native_errors.py': ('proposed_retirement', None, 'One-shot Flutter build with native, Python and Node negative controls'),
    'capture_build_companions.py': ('proposed_retirement', None, 'Runs one real Flutter build and fresh Python and Node controls in the same environment'),
    'build_artifact_report.py': ('proposed_retirement', None, 'Report-only size summary of the Flutter web build'),
    'generate_repository_metadata.py': ('proposed_retirement', None, "Generates the Flutter app's repository record"),
}
BUILD_TOOLS = {
    'android_size.dart': ('proposed_retirement', None, 'Measures the Android arm64 build of the Flutter app'),
    'build_metadata.dart': ('proposed_retirement', None, "Writes the Flutter build's diagnostics metadata"),
    'check.dart': ('proposed_retirement', None, 'Runs the Flutter repository checks (pub get, analyze, test)'),
    'check_versions.dart': ('proposed_retirement', None, 'Reports outdated pub packages (get, shared_preferences, flutter_lints)'),
    'dev.dart': ('proposed_retirement', None, 'Launcher that forwards to the other Dart build tools'),
    'export_pattern_contracts.dart': ('proposed_retirement', None, 'Exports the Dart pattern registry'),
    'inspect.dart': ('proposed_retirement', None, 'Counts and inspects the Dart files of the Flutter repository'),
    'mock_http_server.dart': ('partial', 'MCP lab (MockMcpRoutes, PR #109)', 'Local auth now runs through POST /mock-auth on the existing loopback bridge; original standalone /auth/* HTTP server topology is not reproduced'),
}
WORKFLOWS = {
    'actionlint.yml': ('successor', '.github/workflows/actionlint.yml', ''),
    'non-dart.yml': ('successor', 'the Python and Node test jobs of web-ui (tests/, platform-matrix.yml)', 'The oracles now run as golden fixtures plus web-ui tests'),
    'screen6-responsive.yml': ('successor', 'ScreensBrowserTests (the Hub search stays inside the stage and keeps its text and count across resizes)', 'Chromium; the platform matrix adds Firefox and WebKit'),
    'ui-showcase-comparison.yml': ('successor', 'showcase page and its visual baseline tests', ''),
    'curl-runtime.yml': ('not_absorbed', None, 'Tests real HTTP execution, which web-ui does not do'),
    'dart.yml': ('proposed_retirement', None, 'Flutter analyze and test'),
    'flutter-pages.yml': ('proposed_retirement', None, 'Publishes the Flutter web build'),
    'flutter-pages-audit.yml': ('proposed_retirement', None, 'Audits the published Flutter build'),
    'flutter-audit-contracts.yml': ('proposed_retirement', None, 'Offline contracts of that audit'),
    'flutter-audit-focused-diagnostic.yml': ('proposed_retirement', None, 'Diagnostic of that audit'),
    'web-observations.yml': ('proposed_retirement', None, 'Observes the published Flutter pages'),
    'diagnostics-evidence.yml': ('proposed_retirement', None, 'Screenshots of the Flutter diagnostics overlay'),
    'ios-native.yml': ('proposed_retirement', None, 'iOS build of the Flutter app'),
    'native-error-corpus.yml': ('proposed_retirement', None, 'Native Flutter error corpus'),
    'docker-e2e-verify.yml': ('proposed_retirement', None, 'Snapshots of the Flutter build in Docker'),
    'structure-refactor-validation.yml': ('proposed_retirement', None, 'Smoke of a Dart refactor'),
    'ci-status-label.yml': ('proposed_retirement', None, 'Inactive labelling job of that repository'),
    'claude.yml': ('proposed_retirement', None, 'Assistant workflow of that repository'),
}

_TOKEN = re.compile(r'[A-Za-z_$][A-Za-z_0-9$]*|(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|>>>=|===|!==|>>>|<<=|>>=|\?\?=|\.\.\.|=>|==|!=|<=|>=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|~/|%=|<<|>>|\?\?|\?\.|\.\.|[^\s]')


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _comment_end(text: str, start: int) -> int:
    if text.startswith('//', start):
        end = text.find('\n', start + 2)
        return len(text) if end < 0 else end
    depth, i = 1, start + 2
    while i < len(text):
        if text.startswith('/*', i):
            depth += 1
            i += 2
        elif text.startswith('*/', i):
            depth -= 1
            i += 2
            if not depth:
                return i
        else:
            i += 1
    raise ValueError('Unterminated Dart comment')


def _string_end(text: str, start: int) -> tuple[int, list[str]]:
    raw = text[start] == 'r'
    i = start + int(raw)
    quote = text[i] * (3 if text.startswith(text[i] * 3, i) else 1)
    i += len(quote)
    expressions = []
    while i < len(text):
        if text.startswith(quote, i):
            return i + len(quote), expressions
        if not raw and text[i] == '\\':
            i += 2
        elif not raw and text[i] == '$':
            i += 1
            if i < len(text) and text[i] == '{':
                depth = 1
                i += 1
                expression_start = i
                while i < len(text) and depth:
                    if text.startswith(('//', '/*'), i):
                        i = _comment_end(text, i)
                    elif text[i] in '\"\'' or (text[i] == 'r' and i + 1 < len(text) and text[i + 1] in '\"\''):
                        i, _ = _string_end(text, i)
                    else:
                        depth += (text[i] == '{') - (text[i] == '}')
                        i += 1
                if depth:
                    raise ValueError('Unterminated Dart interpolation')
                expressions.append(text[expression_start:i - 1])
            else:
                match = re.match(r'[A-Za-z_][A-Za-z_0-9]*', text[i:])
                if not match:
                    raise ValueError('Invalid Dart interpolation')
                expressions.append(match.group())
                i += len(match.group())
        else:
            i += 1
    raise ValueError('Unterminated Dart string')


def _shape(text: str) -> str:
    """Heuristic template grouping, not semantic equivalence or migration proof.

    Ignore comments, whitespace, plain string values and numeric literals.
    Retain interpolated expressions as nested shapes; their string labels are
    ignored. Numeric values are deliberately still ignored, so this is not
    a test of behavioral equivalence. Raw strings have no interpolation.
    Only Pattern<number> identifiers are normalized, not arbitrary identifiers.
    Unterminated string/comment/interpolation delimiters fail; this is not
    a Dart parser and does not validate Dart syntax.
    """
    tokens = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith(('//', '/*'), i):
            i = _comment_end(text, i)
        elif text[i] in '\"\'' or (text[i] == 'r' and i + 1 < len(text) and text[i + 1] in '\"\''):
            end, expressions = _string_end(text, i)
            tokens.append(('string', [_shape(expression) for expression in expressions]))
            i = end
        else:
            match = _TOKEN.match(text, i)
            token = match.group()
            if token[0].isdigit():
                tokens.append(('number', ''))
            else:
                token = re.sub(r'^Pattern\d+', 'PatternN', token)
                tokens.append(('code', token))
            i = match.end()
    return hashlib.sha256(json.dumps(tokens, ensure_ascii=False).encode()).hexdigest()


def disposition(name: str, feature: str | None) -> tuple[str, str | None, str]:
    best = None
    for prefix, status, target, remaining in PATH_RULES:
        if name.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, status, target, remaining)
    feature_rule = TARGETS.get(feature) if feature else None
    if feature_rule and (best is None or best[0] == 'lib/screens/'):
        return feature_rule
    if best:
        return best[1], best[2], best[3]
    return 'unreviewed', None, 'Explicit disposition and coverage required'


def _group_file_kinds(root: Path, names: list[str]) -> dict:
    kinds: dict[str, dict] = {}
    for name in names:
        entry = kinds.setdefault(Path(name).name, {'files': 0, 'shapes': set()})
        entry['files'] += 1
        entry['shapes'].add(_shape((root / name).read_text(encoding='utf-8')))
    return {k: {'files': v['files'], 'distinct_shapes': len(v['shapes'])} for k, v in sorted(kinds.items())}


CATALOGUE_GROUPS = {
    'navigation_patterns': ('partial', 'pattern_catalogue (198 rows), 198 screens', 'Per-pattern Flutter views and controllers: see file_kinds; shapes are heuristic groups, not proof of equivalent behavior'),
    'api_patterns': ('partial', 'pattern_catalogue (198 rows), 198 screens', 'As navigation_patterns; service.dart and model.dart have three shapes'),
    'ui_theme_patterns': ('partial', 'pattern_catalogue (198 rows), 198 screens (and the web-ui themes)', 'As navigation_patterns'),
    'data_processing_patterns': ('partial', '14 Python and 5 JavaScript references as pattern_run families; native examples; screens', 'The Flutter views of the data-processing patterns are shown as screens; the view shapes in file_kinds are not reviewed one by one'),
}


def inventory(root: Path) -> dict:
    sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(root), 'diff', '--exit-code', 'HEAD', '--', 'lib', '.github', 'python', 'build_tools', 'ci', 'e2e'], check=True, capture_output=True)
    tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files'], text=True).splitlines()
    dart = sorted(n for n in tracked if n.startswith('lib/') and n.endswith('.dart'))
    files, groups = [], {}
    for name in dart:
        path = Path(name)
        catalog = next((p for p in path.parts if p.endswith('_patterns')), None)
        if catalog:
            groups.setdefault(catalog, []).append(name)
            continue
        feature = path.parts[2] if len(path.parts) > 2 and path.parts[1] == 'features' else None
        status, target, remaining = disposition(name, feature)
        files.append({'path': name, 'sha256': _sha(root / path), 'feature': feature, 'status': status, 'target': target, 'remaining': remaining})
    catalogues = {}
    for group, names in sorted(groups.items()):
        status, target, remaining = CATALOGUE_GROUPS.get(group, ('unreviewed', None, 'Explicit disposition and coverage required'))
        digest = hashlib.sha256('\n'.join(n + ':' + _sha(root / n) for n in names).encode()).hexdigest()
        catalogues[group] = {'files': len(names), 'status': status, 'target': target, 'remaining': remaining, 'file_kinds': _group_file_kinds(root, names), 'tree_digest': digest}

    shared = {_shape((root / n).read_text(encoding='utf-8')) for g in ('navigation_patterns', 'api_patterns', 'ui_theme_patterns') for n in groups.get(g, []) if n.endswith('/view.dart')}
    shared_views = sum(1 for g in ('navigation_patterns', 'api_patterns', 'ui_theme_patterns') for n in groups.get(g, []) if n.endswith('/view.dart'))

    def other(directory: str, suffix: str, table: dict) -> list:
        rows = []
        for name in sorted(n for n in tracked if n.startswith(directory) and n.endswith(suffix) and '/' not in n[len(directory):]):
            status, target, remaining = table.get(Path(name).name, ('unreviewed', None, 'Explicit disposition and coverage required'))
            rows.append({'path': name, 'sha256': _sha(root / name), 'status': status, 'target': target, 'remaining': remaining})
        return rows
    other_sources = {'python_tools': other('python/', '.py', PYTHON_TOOLS), 'build_tools': other('build_tools/', '.dart', BUILD_TOOLS), 'workflows': other('.github/workflows/', '.yml', WORKFLOWS)}
    counts: dict[str, int] = {}
    for rows in (files, *other_sources.values()):
        for row in rows:
            counts[row['status']] = counts.get(row['status'], 0) + 1
    blockers = ['Approve the retirement of every proposed_retirement file, or absorb it', 'Resolve every pending and unreviewed file, group and tool',
                'Record retained/replaced/dropped behavior with tests', 'Validate real-device media/clipboard behavior', 'Export or deliberately retire stored entries',
                'Merge and publish successor pages, then obtain archive approval']
    return {'schema': 'web-ui-flutter-migration/2', 'repository': REPOSITORY, 'source_commit': sha, 'archive_ready': False,
            'scope': 'File inventory and what web-ui did about each file; a status is not a claim that every Dart implementation was reviewed line by line',
            'dart_files': len(files) + sum(c['files'] for c in catalogues.values()), 'navigation_api_ui_view_files': shared_views, 'navigation_api_ui_view_shapes': len(shared), 'status_counts_outside_catalogues': dict(sorted(counts.items())),
            'non_catalogue_files': files, 'catalogues': catalogues, 'other_sources': other_sources, 'archive_blockers': blockers}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='compare with the file on disk instead of writing it')
    args = parser.parse_args(argv)
    text = json.dumps(inventory(args.checkout), ensure_ascii=False, indent=2) + '\n'
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding='utf-8') != text:
            print(f'{args.output} differs from a fresh inventory', file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

