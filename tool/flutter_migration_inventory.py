"""Read-only, stdlib inventory of a Flutter checkout. No network; no archive action."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

TARGETS = {
    'photo_studio': ('partial', 'PhotoStudio, photo_document', 'Native clipboard/share/HEIC and all 41 files need disposition'),
    'composition_generator': ('partial', 'studio_document, progression_notes, studio_audio_plan', 'Audio now opt-in; native random sequence differs intentionally'),
    'now_timeline': ('partial', 'timeline_events, timeline_wall_to_utc, world_document', 'Recurrence and persisted entries are not migrated'),
    'counter_playground': ('successor', 'counter_garden, play_document', 'New reward model; native long-press timing is not copied'),
    'irony_generator': ('successor', 'irony_round, play_document', 'New authored quiz deck; original text corpus remains at source'),
    'coordinate_tool': ('partial', 'coordinates_document', 'Network short-link expansion intentionally excluded'),
    'clipboard_shelf': ('partial', 'shelf_document', 'Native clipboard platform behavior is not equivalent'),
    'http_request_draft': ('partial', 'parse_curl, stub_document', 'Real HTTP execution/authentication needs separate disposition'),
}


def inventory(root: Path) -> dict:
    sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(root), 'diff', '--exit-code', 'HEAD', '--', 'lib'], check=True, capture_output=True)
    tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', 'lib'], text=True).splitlines()
    files, catalogues = [], {}
    for name in sorted(n for n in tracked if n.endswith('.dart')):
        path = Path(name)
        catalog = next((p for p in path.parts if p.endswith('_patterns')), None)
        if catalog:
            group = catalogues.setdefault(catalog, {'files': 0, 'status': 'unreviewed', 'source_sha256': []})
            group['files'] += 1
            group['source_sha256'].append(name + ':' + hashlib.sha256((root / path).read_bytes()).hexdigest())
            continue
        feature = path.parts[2] if len(path.parts) > 2 and path.parts[1] == 'features' else None
        status, target, gap = TARGETS.get(feature, ('unreviewed', None, 'Explicit disposition and coverage required'))
        files.append({'path': name, 'sha256': hashlib.sha256((root / path).read_bytes()).hexdigest(),
                      'feature': feature, 'status': status, 'target': target, 'remaining': gap})
    for group in catalogues.values():
        group['tree_digest'] = hashlib.sha256('\n'.join(group.pop('source_sha256')).encode()).hexdigest()
    return {'schema': 'web-ui-flutter-migration/1', 'repository': 'myon-bioinformatics/flutter_navigation_basic',
            'source_commit': sha, 'archive_ready': False,
            'scope': 'File inventory and feature-level mapping; not a claim every Dart implementation was reviewed',
            'dart_files': len(files) + sum(c['files'] for c in catalogues.values()),
            'non_catalogue_files': files, 'catalogues': catalogues,
            'archive_blockers': ['Resolve every unreviewed file and catalogue', 'Record retained/replaced/dropped behavior with tests',
                                 'Validate real-device media/clipboard behavior', 'Export or deliberately retire stored entries',
                                 'Merge and publish successor pages, then obtain archive approval']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = inventory(args.checkout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()
