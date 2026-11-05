"""Compare unmodified Dart fixture auth sources with Python over one corpus.

python -S tool/auth_parity.py /path/to/flutter_navigation_basic
Requires Dart (and pub access for the original crypto ^3.0.7 dependency).
No Flutter SDK, application bootstrap, external authentication or network requests.
Only `dart pub get` obtains test dependencies. Sources must match the pinned hashes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import web_ui

# Source commit is recorded with the corpus. Hashes verify the actual Dart bytes.
SOURCES = {
    'mock_auth.dart': 'f54ec9e9b064c3bb5f36d0c6f0efc6e9e47fdcafb02f699ff5e09a0231e47783',
    'digest_nc.dart': 'cf1d48ff8201900c606811f1a70375b5e18ae51c62af427badd479c3aabe8825',
}

DART_PRODUCER = r'''
import 'dart:convert';
import 'dart:io';
import 'mock_auth.dart';
import 'digest_nc.dart';

void main(List<String> args) {
  final corpus = jsonDecode(File(args.single).readAsStringSync()) as Map;
  final outputs = <Object?>[];
  for (final session in corpus['sessions'] as List) {
    final handler = MockAuthHandler(clock: () => DateTime.fromMillisecondsSinceEpoch((corpus['clock'] as int) * 1000, isUtc: true));
    final answers = <Object?>[];
    for (final request in session['requests'] as List) {
      final r = request as Map;
      final pairs = r['query_pairs'] == null ? null : [for (final p in r['query_pairs'] as List) (name: p[0] as String, value: p[1] as String)];
      final answer = handler.handle(method: (r['method'] ?? 'GET') as String, path: r['path'] as String,
        headers: Map<String,String>.from(r['headers'] ?? {}), query: Map<String,String>.from(r['query'] ?? {}),
        requestTarget: r['request_target'] as String?, body: r['body'] as String?, queryPairs: pairs);
      answers.add(answer == null ? null : {'status': answer.statusCode, 'headers': answer.headers, 'body': answer.body});
    }
    outputs.add({'name': session['name'], 'answers': answers});
  }
  print(jsonEncode({'sessions': outputs,
    'nc': [for (final value in corpus['nc'] as List) DigestNc.tryParse(value as String)],
    'format': [for (final value in corpus['format'] as List) DigestNc.format(value as int)],
    'hmac': [for (final r in corpus['hmac'] as List) MockAuthHandler.hmacSignature(method:r['method'],path:r['path'],timestamp:r['timestamp'],nonce:r['nonce'],queryString:r['query_string'],body:r['body'])],
    'digest': [for (final r in corpus['digest'] as List) MockAuthHandler.digestResponse(method:r['method'],uri:r['uri'],username:'demo',password:'s3cret',realm:'mock',nonce:'demo-digest-nonce',nc:r['nc'],cnonce:r['cnonce'])],
    'query': [for (final pairs in corpus['query'] as List) MockAuthHandler.encodeQueryPairs([for (final p in pairs) (name:p[0] as String,value:p[1] as String)])]
  }));
}
'''


def python_answers(corpus):
    sessions = []
    for session in corpus['sessions']:
        handler = web_ui.MockAuthHandler(clock=lambda: corpus['clock'])
        sessions.append({'name': session['name'], 'answers': [handler.handle(r) for r in session['requests']]})
    return {'sessions': sessions, 'nc': [web_ui.digest_nc_parse(v) for v in corpus['nc']],
            'format': [web_ui.digest_nc_format(v) for v in corpus['format']],
            'hmac': [web_ui.auth_hmac_signature(**r) for r in corpus['hmac']],
            'digest': [web_ui.auth_digest_response(**r) for r in corpus['digest']],
            'query': [web_ui.auth_query_pairs(p) for p in corpus['query']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('flutter_checkout', type=Path)
    args = parser.parse_args()
    corpus_path = ROOT / 'tests/fixtures/mock_auth_contract.json'
    corpus = json.loads(corpus_path.read_text())
    with tempfile.TemporaryDirectory(prefix='web-ui-auth-dart-') as tmp:
        project = Path(tmp)
        for name, expected in SOURCES.items():
            path = args.flutter_checkout / 'lib/shared/http' / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise SystemExit('source hash mismatch: ' + str(path))
            shutil.copyfile(path, project / name)
        (project / 'pubspec.yaml').write_text("name: auth_fixture_parity\nenvironment:\n  sdk: '>=3.12.0 <4.0.0'\ndependencies:\n  crypto: 3.0.7\n")
        (project / 'main.dart').write_text(DART_PRODUCER)
        subprocess.run(['dart', 'pub', 'get'], cwd=project, check=True, timeout=120)
        dart = subprocess.run(['dart', 'run', 'main.dart', str(corpus_path)], cwd=project, check=True, capture_output=True, text=True, timeout=60)
        expected = json.loads(dart.stdout)
    actual = python_answers(corpus)
    if actual != expected:
        # Print only public fixture output; never credentials from a live service.
        for key in expected:
            if actual[key] != expected[key]:
                if key == 'sessions':
                    for dart_session, python_session in zip(expected[key], actual[key]):
                        for index, (dart_answer, python_answer) in enumerate(zip(dart_session['answers'], python_session['answers'])):
                            if dart_answer != python_answer:
                                print(json.dumps({'session': dart_session['name'], 'index': index, 'dart': dart_answer, 'python': python_answer}, ensure_ascii=False))
                else:
                    print(json.dumps({'section': key, 'dart': expected[key], 'python': actual[key]}, ensure_ascii=False))
        raise SystemExit('Dart/Python auth contract mismatch')
    print(f"Dart/Python auth parity: {sum(len(s['requests']) for s in corpus['sessions'])} requests, "
          f"{sum(len(corpus[k]) for k in ('nc','format','hmac','digest','query'))} helper vectors; source {corpus['source_commit']}")


if __name__ == '__main__':
    main()
