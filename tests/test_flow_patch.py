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
        for raw in (b"\\xff", b" " * (320 * 1024 + 1)):
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

if __name__ == "__main__":
    unittest.main()
