import json
from pathlib import Path
import subprocess
import sys
import unittest

from tool.flow_patch import canonical, patch_flow

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "examples/pr-flow.json").read_text(encoding="utf-8"))


class FlowPatchTests(unittest.TestCase):
    def test_roundtrip_and_no_mutation(self):
        before = json.dumps(SPEC, ensure_ascii=False)
        patched = patch_flow(SPEC, [
            {"path": "/sources/0/note", "value": "入力・更新"},
            {"path": "/steps/0/title", "value": "統合 #120"},
        ])
        self.assertEqual(json.dumps(SPEC, ensure_ascii=False), before)
        self.assertEqual(patched["sources"][0]["note"], "入力・更新")
        self.assertEqual(canonical(patched), patched)
        self.assertEqual(patch_flow(patched, []), patched)

    def test_invalid_patch_is_atomic(self):
        before = json.dumps(SPEC, ensure_ascii=False)
        for operations in (
            [{"path": "/title", "value": "changed"}, {"path": "/steps/99/title", "value": "bad"}],
            [{"path": "/steps/01/title", "value": "bad"}],
            [{"path": "/sources/0/title", "value": "<script>\n"}],
            [{"path": "/steps/0/html", "value": "x"}],
            [{"path": "/steps/0/title", "value": 42}],
        ):
            with self.subTest(operations=operations), self.assertRaises(ValueError):
                patch_flow(SPEC, operations)
            self.assertEqual(json.dumps(SPEC, ensure_ascii=False), before)

    def test_cli_rejects_malformed_utf8_and_oversize(self):
        for raw in (b"\xff", b" " * (320 * 1024 + 1)):
            with self.subTest(size=len(raw)):
                for command in ([sys.executable, "-S", "-m", "tool.flow_patch"],
                                ["node", "js/flow-patch.cjs"]):
                    result = subprocess.run(command, input=raw, capture_output=True, cwd=ROOT)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, b"")

    def test_python_node_cli_parity(self):
        data = {"spec": SPEC, "patch": [{"path": "/steps/1/note", "value": "CI完了"}]}
        input_text = json.dumps(data, ensure_ascii=False)
        py = subprocess.run([sys.executable, "-S", "-m", "tool.flow_patch"], input=input_text,
                            text=True, capture_output=True, cwd=ROOT)
        node = subprocess.run(["node", "js/flow-patch.cjs"], input=input_text,
                              text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(py.returncode, 0, py.stderr)
        self.assertEqual(node.returncode, 0, node.stderr)
        self.assertEqual(json.loads(py.stdout), json.loads(node.stdout))

    def test_boundary_parity_and_atomic_invalid_batches(self):
        cases = [
            ("/steps/0/note", None, False),
            ("/sources_label", None, False),
            ("/steps/0/title", "😀" * 120, True),
            ("/steps/0/title", "😀" * 121, False),
            ("/sources/0/note", "😀" * 240, True),
            ("/sources/0/note", "😀" * 241, False),
            ("/steps/0/title", "\ufeff", True),
            ("/steps/0/title", "\x85", False),
            ("/steps/0/title", "\u3000", False),
            ("/steps/0/title", "\ud800", False),
            ("/steps/0/title", "\udfff", False),
        ]
        for path, value, accepted in cases:
            operations = [{"path":"/title", "value":"first valid edit"}, {"path":path,"value":value}]
            original = json.dumps(SPEC)
            data = json.dumps(dict(spec=SPEC, patch=operations)).encode()
            with self.subTest(path=path, value=repr(value)):
                results = [subprocess.run(command, input=data, capture_output=True, cwd=ROOT)
                           for command in ([sys.executable,"-S","-m","tool.flow_patch"],
                                           ["node","js/flow-patch.cjs"])]
                self.assertEqual([r.returncode for r in results], [0,0] if accepted else [2,2])
                if accepted:
                    self.assertEqual(json.loads(results[0].stdout), json.loads(results[1].stdout))
                else:
                    self.assertEqual([r.stdout for r in results], [b"",b""])
                    with self.assertRaises(ValueError): patch_flow(SPEC, operations)
                self.assertEqual(json.dumps(SPEC), original)

    def test_native_clis_reject_invalid_utf8_inside_valid_json_and_bom(self):
        patch = json.dumps(dict(spec=SPEC, patch=[{"path":"/title","value":"MARKER"}])).encode()
        flow = json.dumps(SPEC).encode()
        for document, modules in ((patch, ("tool.flow_patch","js/flow-patch.cjs")),
                                  (flow, ("tool.flow_diagram","js/flow.cjs"))):
            invalid = document.replace(b'MARKER', b'\xff') if modules[0].endswith('patch') else document.replace(b'"title":', b'"title":"\xff", "title":', 1)
            for raw in (invalid, b"\xef\xbb\xbf" + document):
                for command in ([sys.executable,"-S","-m",modules[0]], ["node",modules[1]]):
                    result = subprocess.run(command, input=raw, capture_output=True, cwd=ROOT)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, b"")

if __name__ == "__main__":
    unittest.main()
