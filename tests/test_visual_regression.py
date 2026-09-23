from pathlib import Path
import tempfile
import unittest

from scripts.check_visual_regression import compare


def _png(width=1, height=1):
    # The checker validates the PNG signature and IHDR width/height bytes only.
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


class VisualRegressionTest(unittest.TestCase):
    def test_missing_candidate_directory_is_setup_error(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / "missing"
            self.assertEqual(compare(missing, Path(root) / "baseline", False), 2)

    def test_no_matching_candidates_is_setup_error(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "other.png").write_bytes(_png())
            self.assertEqual(compare(root_path, root_path / "baseline", False), 2)

    def test_candidate_mode_allows_missing_baseline(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "web-ui-contract.png").write_bytes(_png())
            self.assertEqual(compare(root_path, root_path / "baseline", False), 0)

    def test_enforcement_mode_rejects_missing_baseline(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "web-ui-contract.png").write_bytes(_png())
            self.assertEqual(compare(root_path, root_path / "baseline", True), 1)

    def test_pattern_can_limit_enforcement_scope(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline"
            baseline.mkdir()
            contract = root_path / "web-ui-contract-v1.png"
            gallery = root_path / "web-ui-gallery.png"
            contract.write_bytes(_png(2, 3))
            gallery.write_bytes(_png(4, 5))
            (baseline / contract.name).write_bytes(contract.read_bytes())

            self.assertEqual(
                compare(
                    root_path,
                    baseline,
                    True,
                    pattern="web-ui-contract-*.png",
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
