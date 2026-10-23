"""Exercise copied artifacts in isolated stdlib-only interpreters."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import web_ui

ROOT = Path(__file__).resolve().parents[1]


def test_embedded_launcher_matches_locked_vendor():
    assert web_ui._EMBEDDED_NODE_LAUNCH_SOURCE.encode() == (ROOT / 'vendor/node_launch.py').read_bytes()


@pytest.mark.parametrize('vendor', [False, True])
@pytest.mark.parametrize('case', ['html', 'success', 'nonzero', 'timeout', 'missing', 'old'])
def test_copied_artifact(tmp_path, vendor, case):
    shutil.copyfile(ROOT / 'web_ui.py', tmp_path / 'web_ui.py')
    if vendor:
        (tmp_path / 'vendor').mkdir()
        shutil.copyfile(ROOT / 'vendor/node_launch.py', tmp_path / 'vendor/node_launch.py')
    code = '''
import web_ui as u
import subprocess
'''
    code += {
        'html': '''
u.shutil.which = lambda *a: None
assert 'hello' in u.render_document('hello')
assert u._NODE_LAUNCH is None
''',
        'success': '''
p = u.run_node('-e', 'process.stdout.write("hello"+String.fromCharCode(13,10)); process.stderr.write("err"+String.fromCharCode(13));')
assert (p.returncode, p.stdout, p.stderr) == (0, 'hello\\n', 'err\\n')
assert u.run_node(input='console.log(42)').stdout == '42\\n'
''',
        'nonzero': '''
p = u.run_node('-e', 'console.error("bad"); process.exit(7)')
assert p.returncode == 7 and p.stderr == 'bad\\n'
try:
    u.run_node('-e', 'process.exit(7)', check=True)
except u._node_launch_module().LaunchError as e:
    assert e.status == 7
else:
    raise AssertionError('missing CalledProcessError')
''',
        'timeout': '''
try:
    u.run_node('-e', 'console.log("ready"); console.error("waiting"); setTimeout(()=>{}, 30000)', timeout=1)
except subprocess.TimeoutExpired as e:
    assert e.output == b'ready\\n' and e.stderr == b'waiting\\n'
else:
    raise AssertionError('missing timeout')
''',
        'missing': '''
u.shutil.which = lambda *a: None
try:
    u.run_node('-e', '42')
except RuntimeError as e:
    assert 'node executable not found' in str(e)
else:
    raise AssertionError('missing failure')
''',
        'old': '''
launcher = u._node_launch_module()
launcher.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a[0], 0, b'v20.0.0', b'')
try:
    u.run_node('-e', '42')
except RuntimeError as e:
    assert 'found Node 20' in str(e)
else:
    raise AssertionError('old Node accepted')
''',
    }[case]
    done = subprocess.run([sys.executable, '-I', '-S', '-c',
                           'import sys; sys.path.insert(0, ' + repr(str(tmp_path)) + ');' + code],
                          cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
