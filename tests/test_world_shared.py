"""Opt-in shared board contract; no network calls or public writes."""
import subprocess
from pathlib import Path
import pytest
from support import node26
import web_ui as ui


def spec():
    value = ui.example_data('world')
    value['board']['shared_issue'] = 'myon-bioinformatics/PySaiyanWeBoo/123'
    return value


def test_opt_in_and_local_form():
    value = spec()
    html = ui.world_html(value)
    assert 'ui-board-post' in html and 'ui-board-shared' in html
    assert 'issues/123#new_comment_field' in html
    assert 'credentials' not in html  # secrets are never embedded in HTML
    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert ui.world_validate(ui.world_validate(value)) == ui.world_validate(value)
    del value['board']['shared_issue']
    assert 'data-shared-refresh' not in ui.world_html(value)


@pytest.mark.parametrize('bad', ['', 'https://github.com/a/b/1', 'a/b/0', 'a/b/-1', 'a/b/1?token=x', 'a/b/1/extra', True, {}, 'a/../../1', 'a/../1', 'a/./1'])
def test_invalid_target(bad):
    value = spec()
    value['board']['shared_issue'] = bad
    with pytest.raises(ValueError):
        ui.world_validate(value)


def test_shared_node(tmp_path):
    node = node26() or pytest.skip('Node 26+ required')
    module = tmp_path / 'shared.mjs'
    module.write_text(ui.WORLD_JS.removesuffix('bindWorlds();\n') + (Path(__file__).parent / 'fixtures/world_shared_harness.js').read_text())
    subprocess.run([node, str(module)], check=True)


def test_approved_example_destination():
    value = ui.example_data('world')
    assert value['board']['shared_issue'] == 'myon-bioinformatics/PySaiyanWeBoo/110'
    html = ui.world_document(value)
    assert 'https://github.com/myon-bioinformatics/PySaiyanWeBoo/issues/110#new_comment_field' in html
    assert 'issues/123#new_comment_field' not in html
