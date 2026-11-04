"""Record the verdicts of flutter_navigation_basic's own contract checks as golden values for ``web_ui.py --pattern contract``.

Run it against a checkout of the original (read only)::

    python3 tool/contract_golden.py /path/to/flutter_navigation_basic --output tests/fixtures/contract_golden.json

The originals are python/metadata_contracts.py (``validate_screens``, ``validate_locales``), python/header_contracts.py (``validate``) and python/gesture_paint.py
(``check_swap`` on the vendored Pillow subset). Every case is a seeded mutation of a base document that web-ui keeps next to the fixture (the screens asset, the screen texts) or that
this file builds (a header snapshot, synthetic screenshots); the fixture records the mutation, the SHA-256 of the mutated document (so a test that applies the mutation itself can prove it
built the same one) and what the original said. ``--check`` rebuilds the fixture and exits 1 if the file on disk differs.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import io
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import web_ui  # noqa: E402

SEED = "contract-golden/1"
DUMMY_KEYS = {"common.x": "x", "home.x": "x", "coordinate.x": "x", "photoStudio.x": "x", "nowTimeline.x": "x", "urlParameters.case": "x {urlParamCaseId}"}
TEXT_FIELDS = ("name", "title", "description", "category", "navigationPattern", "apiPattern", "themePattern", "dataPattern")
HEADER = ("shared-header-title", "shared-header-home", "shared-header-favorite", "shared-header-menu")


def digest(document) -> str:
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def apply(document, operations):
    """The mutation language shared with the tests: ``{"path": [...], "set": value}``, ``{"path": [...], "delete": true}``, ``{"drop": index}``, ``{"append_copy": index}`` and ``{"swap": [i, j]}`` (rows)."""
    document = copy.deepcopy(document)
    for operation in operations:
        if "drop" in operation:
            del document[operation["drop"]]
        elif "append_copy" in operation:
            document.append(copy.deepcopy(document[operation["append_copy"]]))
        elif "swap" in operation:
            i, j = operation["swap"]
            document[i], document[j] = document[j], document[i]
        else:
            target = document
            for step in operation["path"][:-1]:
                target = target[step]
            if operation.get("delete"):
                del target[operation["path"][-1]]
            else:
                target[operation["path"][-1]] = copy.deepcopy(operation["set"])
    return document


def verdict(check, document) -> bool:
    try:
        check(document)
    except Exception:  # the originals assert; a KeyError or TypeError on a malformed document is a refusal as well
        return False
    return True


def load_originals(checkout: Path):
    sys.path.insert(0, str(checkout / "python"))
    import gesture_paint
    import header_contracts
    import metadata_contracts
    return metadata_contracts, header_contracts, gesture_paint


def screens_cases(rng, rows, oracle):
    pool = [None, "", " ", "wrong", 0, 7, [], ["a"], {}, 1.5]
    cases = [[]]
    detail_rows = [i for i, row in enumerate(rows) if row.get("detail")]
    for _ in range(420):
        operations = []
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            kind = rng.choice(("field", "field", "field", "delete", "detail", "detail_text", "points", "id", "structure", "unique"))
            index = rng.randrange(len(rows))
            if kind == "field":
                field = rng.choice(TEXT_FIELDS + ("domainKey", "templateJa", "useCaseKey", "templateOverride", "tags"))
                values = [value for value in pool + [rows[rng.randrange(len(rows))].get(field)] if not (field == "templateOverride" and value is None)]
                operations.append({"path": [index, field], "set": rng.choice(values)})
            elif kind == "delete":
                field = rng.choice(TEXT_FIELDS + ("domainKey", "templateJa", "useCaseKey", "emoji", "screenDataId", "detail"))
                if field in rows[index]:
                    operations.append({"path": [index, field], "delete": True})
            elif kind == "detail":
                operations.append({"path": [index, "detail"], "set": rng.choice([None, {}, "text", [], {"purpose": "p", "when": "w", "points": ["a", "b", "c"], "pitfall": "x", "snippet": "s"}, copy.deepcopy(rows[detail_rows[0]]["detail"])])})
            elif kind == "detail_text":
                index = rng.choice(detail_rows)
                operations.append({"path": [index, "detail", rng.choice(("purpose", "when", "pitfall", "snippet"))], "set": rng.choice([None, "", 5, [], "ok"])})
            elif kind == "points":
                index = rng.choice(detail_rows)
                operations.append({"path": [index, "detail", "points"], "set": rng.choice([[], ["a"], ["a", "b"], ["a", "b", "c", "d"], ["a", "", "c"], ["a", None, "c"], ["a", 1, "c"], None, ["x", "y", "z"]])})
            elif kind == "id":
                operations.append({"path": [index, "screenDataId"], "set": rng.choice([0, -1, 199, 200, "5", None, 1.0 + rng.randrange(198) + 0.5, rng.randrange(1, 199), rng.randrange(1, 199)])})
            elif kind == "structure":
                operations.append(rng.choice(({"drop": index}, {"append_copy": index}, {"swap": [index, rng.randrange(len(rows))]})))
            else:
                other = rng.randrange(len(rows))
                operations.append({"path": [index, rng.choice(("useCaseKey", "emoji"))], "set": None})
                operations[-1]["set"] = rows[other][operations[-1]["path"][1]]
        cases.append(operations)
    out = []
    for operations in cases:
        try:
            document = apply(rows, operations)
        except (KeyError, IndexError, TypeError):
            continue
        out.append({"mutation": operations, "sha256": digest(document), "valid": verdict(oracle, document)})
    return out


def locale_base(locales):
    return {code: {**table, **DUMMY_KEYS} for code, table in locales.items()}


def locales_cases(rng, base, oracle):
    codes = sorted(base)
    keys = sorted(base["eng"])
    placeholder_keys = ("urlParameters.case", "generic.screenFallbackTitle", "patternTemplate.screenIdLabel")
    cases = [[]]
    for _ in range(260):
        operations = []
        for _ in range(rng.choice((1, 1, 1, 1, 2))):
            code, key = rng.choice(codes), rng.choice(keys)
            kind = rng.choice(("blank", "delete_key", "extra_key", "drop_locale", "add_locale", "placeholder", "id_placeholder", "eng_empty", "type", "retext", "retext", "retext", "add_key_all", "add_key_all", "same_placeholder"))
            if kind == "retext":
                if "{" not in base[code][key]:
                    operations.append({"path": [code, key], "set": rng.choice(["別の文", "other text", "  padded  ", "x"])})
            elif kind == "add_key_all":
                for each in codes:
                    operations.append({"path": [each, "added.key"], "set": "text"})
            elif kind == "same_placeholder":
                key = rng.choice(placeholder_keys)
                operations.append({"path": [code, key], "set": "前 " + base["eng"][key] + " 後" if code != "eng" else base["eng"][key] + "."})
            elif kind == "blank":
                operations.append({"path": [code, key], "set": rng.choice(["", " ", "\t\n", None, 0, []])})
            elif kind == "delete_key":
                operations.append({"path": [code, key], "delete": True})
            elif kind == "extra_key":
                operations.append({"path": [code, "extra.key"], "set": "x"})
            elif kind == "drop_locale":
                operations.append({"path": [code], "delete": True})
            elif kind == "add_locale":
                operations.append({"path": ["xyz"], "set": copy.deepcopy(base["eng"])})
            elif kind == "placeholder":
                key = rng.choice(placeholder_keys)
                operations.append({"path": [code, key], "set": rng.choice(["no placeholder", "{wrong}", "{wrong} {x}"])})
            elif kind == "id_placeholder":
                operations.append({"path": [code, "urlParameters.case"], "set": "x {urlParamCaseId} {id}"})
            elif kind == "eng_empty":
                operations.append({"path": ["eng"], "set": rng.choice([{}, [], None])})
            else:
                operations.append({"path": [code], "set": rng.choice([[], "text", None, 5])})
        cases.append(operations)
    out = []
    for operations in cases:
        try:
            document = apply(base, operations)
        except (KeyError, IndexError, TypeError):
            continue
        out.append({"mutation": operations, "sha256": digest(document), "valid": verdict(oracle, document)})
    return out


def header_snapshot():
    return {"schemaVersion": 1, "route": "/hub", "title": "Navigation Hub 🗺️", "viewport": {"width": 390}, "requiresSecondary": True, "boxes": {
        "shared-header-title": {"x": 8, "y": 14, "width": 180, "height": 28},
        "shared-header-home": {"x": 230, "y": 4, "width": 48, "height": 48},
        "shared-header-favorite": {"x": 278, "y": 4, "width": 48, "height": 48},
        "shared-header-menu": {"x": 326, "y": 4, "width": 48, "height": 48},
        "shared-header-secondary": {"x": 0, "y": 56, "width": 390, "height": 48}}}


def layout_cases(rng, base, oracle):
    names = list(base["boxes"])
    deltas = (-1000, -49, -9, -3, -2.5, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 2.5, 3, 9, 49, 1000)
    cases = [[], [{"path": ["requiresSecondary"], "set": False}]]
    for _ in range(420):
        operations = []
        for _ in range(rng.choice((1, 1, 2, 3))):
            name, field = rng.choice(names), rng.choice(("x", "y", "width", "height"))
            kind = rng.choice(("delta", "delta", "delta", "value", "delete", "toggle", "viewport"))
            if kind == "delta":
                operations.append({"path": ["boxes", name, field], "set": base["boxes"][name][field] + rng.choice(deltas)})
            elif kind == "value":
                operations.append({"path": ["boxes", name, field], "set": rng.choice([0, -1, 1, 390, 391, 392, None, "12"])})
            elif kind == "delete":
                operations.append({"path": ["boxes", name], "delete": True} if rng.random() < 0.5 else {"path": ["boxes", name, field], "delete": True})
            elif kind == "toggle":
                operations.append({"path": ["requiresSecondary"], "set": rng.choice([True, False])})
            else:
                operations.append({"path": ["viewport", "width"], "set": rng.choice([320, 360, 389, 390, 391, 392, 400, 0, -5])})
        cases.append(operations)
    out = []
    for operations in cases:
        try:
            document = apply(base, operations)
        except (KeyError, IndexError, TypeError):
            continue
        out.append({"mutation": operations, "sha256": digest(document), "valid": verdict(oracle, document)})
    return out


def make_raster(width, height, fill):
    return bytearray(bytes(fill) * (width * height))


def paint(raster, width, box, color, rng, noise):
    left, top, right, bottom = box
    for y in range(top, bottom):
        for x in range(left, right):
            pixel = list(color)
            if noise and rng.random() < noise:
                pixel[rng.randrange(4)] = rng.randrange(256)
            raster[(y * width + x) * 4:(y * width + x) * 4 + 4] = bytes(pixel)


def swap_cases(rng, gesture_paint):
    import image_diff
    backend = image_diff._module._require_image_backend()
    out = []
    for index in range(150):
        scale = rng.choice((1, 1, 1, 2, 2, 3, 1.5, 2.5, 2.625, 0.5))
        card_w, card_h = rng.randrange(18, 28), rng.randrange(18, 24)
        fractional = rng.random() < 0.25
        x0 = rng.choice((0, 1, 2, 3, 4, 5)) + (0.5 if fractional else 0)
        y0 = rng.choice((0, 1, 2, 3, 4)) + (0.5 if fractional and rng.random() < 0.5 else 0)
        gap = rng.randrange(0, 8)
        second = card_w + (1 if rng.random() < 0.05 else 0)
        slots = [{"x": x0, "y": y0, "width": card_w, "height": card_h}, {"x": x0 + card_w + gap, "y": y0, "width": second, "height": card_h}]
        view_w = int(x0 + card_w + gap + second) + 1 + rng.randrange(0, 12)
        view_h = int(y0 + card_h) + 1 + rng.randrange(0, 12)
        width, height = round(view_w * scale), round(view_h * scale)
        geometry = {"device_scale_factor": scale, "viewport": {"width": view_w, "height": view_h}, "slots": slots}
        before = make_raster(width, height, (250, 250, 250, 255))
        boxes = [tuple(round(v * scale) for v in (s["x"] + 8, s["y"] + 8, s["x"] + s["width"] - 8, s["y"] + s["height"] - 8)) for s in slots]
        ok_boxes = all(0 <= b[0] < b[2] <= width and 0 <= b[1] < b[3] <= height for b in boxes)
        colors = [(rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.choice((255, 255, 128))) for _ in range(2)]
        noise = rng.choice((0, 0, 0.1))
        if ok_boxes:
            for box, color in zip(boxes, colors):
                paint(before, width, box, color, rng, noise)
        after = bytearray(before)
        mode = rng.choice(("swap", "swap", "swap", "swap", "pixel", "stale", "other", "alpha", "blank", "size", "scale", "slots", "viewport"))
        if ok_boxes and mode in ("swap", "pixel", "alpha", "blank", "other"):
            crops = []
            for box in boxes:
                crops.append([bytes(before[(y * width + box[0]) * 4:(y * width + box[2]) * 4]) for y in range(box[1], box[3])])
            for slot_index, box in enumerate(boxes):
                source = crops[1 - slot_index]
                for row, y in enumerate(range(box[1], box[3])):
                    line = source[row] if row < len(source) else b""
                    wanted = (box[2] - box[0]) * 4
                    after[(y * width + box[0]) * 4:(y * width + box[0]) * 4 + wanted] = line[:wanted].ljust(wanted, b"\x00")
        if ok_boxes and mode in ("pixel", "alpha"):
            box = boxes[rng.randrange(2)]
            x, y = rng.randrange(box[0], box[2]), rng.randrange(box[1], box[3])
            channel = 3 if mode == "alpha" else rng.randrange(3)
            after[(y * width + x) * 4 + channel] = (after[(y * width + x) * 4 + channel] + rng.choice((1, 5, 100))) % 256
        if ok_boxes and mode == "blank":
            before = bytearray(make_raster(width, height, (250, 250, 250, 255)))
            after = bytearray(before)
        if mode == "other" and ok_boxes:
            box = boxes[rng.randrange(2)]
            paint(after, width, box, (1, 2, 3, 255), rng, 0)
        if mode == "scale":
            geometry["device_scale_factor"] = rng.choice((0, -1, -2.5, None, "2", 0.0))
        if mode == "slots":
            geometry["slots"] = rng.choice(([], slots[:1], slots + slots[:1], [slots[0], {"x": 0, "y": 0, "width": 15, "height": 30}], [slots[0], {"x": -20, "y": 0, "width": 40, "height": 30}],
                                              [{"x": None, "y": 0, "width": 40, "height": 30}, slots[1]], [slots[0], {"x": 0, "y": 0, "width": 39, "height": 30}], [slots[0], {"y": 0}]))
        if mode == "viewport":
            geometry["viewport"] = rng.choice(({"width": view_w + 2, "height": view_h}, {"width": view_w, "height": view_h - 3}, {"width": view_w + 1, "height": view_h}, {"width": "a", "height": view_h}, {"width": view_w}))
        before_png, after_png = web_ui.photo_png(width, height, bytes(before)), web_ui.photo_png(width + (1 if mode == "size" else 0), height, bytes(after) if mode != "size" else bytes(make_raster(width + 1, height, (9, 9, 9, 255))))
        try:
            result = gesture_paint.check_swap(backend.Image.open(io.BytesIO(before_png)).convert("RGBA"), backend.Image.open(io.BytesIO(after_png)).convert("RGBA"), copy.deepcopy(geometry))
            expected = {"ok": bool(result["matches"]), "pixel_crops": [list(box) for box in result["pixel_crops"]],
                        "comparisons": [{"changed": c["changed"], "ratio": c["ratio"], "bbox": list(c["bbox"]) if c["bbox"] else None, "max_delta": c["max_delta"], "differs": c["differs"]} for c in result["comparisons"]]}
        except ValueError as error:
            expected = {"error": str(error)}
        except Exception as error:  # a malformed geometry makes the original raise TypeError or KeyError: the contract is "refused"
            expected = {"error": "", "original": type(error).__name__}
        out.append({"mode": mode, "before": base64.b64encode(before_png).decode(), "after": base64.b64encode(after_png).decode(), "geometry": geometry, "expected": expected})
    return out


def build(checkout: Path) -> dict:
    metadata, header, gesture = load_originals(checkout)
    rng = random.Random(SEED)
    rows = json.loads((ROOT / "tests/fixtures/screens_asset.json").read_text(encoding="utf-8"))["screens"]
    locales = json.loads((ROOT / "tests/fixtures/screen_text_golden.json").read_text(encoding="utf-8"))["locales"]
    base_locales = locale_base(locales)
    snapshot = header_snapshot()
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    sources = {name: hashlib.sha256((checkout / "python" / name).read_bytes()).hexdigest() for name in ("metadata_contracts.py", "header_contracts.py", "gesture_paint.py")}
    return {"schema": "web-ui-contract-golden/1", "source": {"repository": "myon-bioinformatics/flutter_navigation_basic", "commit": commit, "sha256": sources},
            "screens": screens_cases(rng, rows, metadata.validate_screens),
            "locales": locales_cases(rng, base_locales, metadata.validate_locales),
            "layout": {"snapshot": snapshot, "cases": layout_cases(rng, snapshot, header.validate)},
            "swap": swap_cases(rng, gesture)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/fixtures/contract_golden.json")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file on disk is not what this run builds")
    args = parser.parse_args(argv)
    text = json.dumps(build(args.checkout), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if args.check:
        same = args.output.exists() and args.output.read_text(encoding="utf-8") == text
        print("contract golden: " + ("unchanged" if same else "differs"))
        return 0 if same else 1
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
