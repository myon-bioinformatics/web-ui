#!/usr/bin/env python3
"""Portable collection query: JSON on stdin -> JSON on stdout (stdlib only).

Filter (query, facets, ranges), then sort, then window (offset/limit), then optionally group.
Node reaches this tool through vendor/py_launch.cjs (no Node twin); domain-specific
browser filters and callbacks remain in the collection.js module (web_ui.js_source).
Sort, ranges, window and grouping come from flutter_navigation_basic python/collection_query_patterns.py
(its facet/tag filters were duplicates of the facets here and are not carried over).
"""
from __future__ import annotations

import json
import math
import sys


def _text(value):
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value).strip().lower()


def _equal(actual, expected):
    # Match JavaScript strict equality for JSON scalar values (not Python 0 == False).
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        return isinstance(expected, (int, float)) and not isinstance(expected, bool) and actual == expected
    return type(actual) is type(expected) and actual == expected


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _ranges(spec):
    if not isinstance(spec, dict) or any(not isinstance(k, str) or not k for k in spec):
        raise ValueError("ranges must map field names to {min, max}")
    out = {}
    for key, bounds in spec.items():
        if not isinstance(bounds, dict) or not bounds or set(bounds) - {"min", "max"} \
                or any(not _number(v) for v in bounds.values()) \
                or ("min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]):
            raise ValueError("a range has numeric min and/or max, with min <= max")
        out[key] = bounds
    return out


def _sorts(spec):
    keys = [spec] if isinstance(spec, dict) else spec
    if not isinstance(keys, list) or not keys:
        raise ValueError("sort is {key, descending} or a nonempty list of them")
    out = []
    for entry in keys:
        if not isinstance(entry, dict) or set(entry) - {"key", "descending"} or not isinstance(entry.get("key"), str) \
                or not entry["key"] or not isinstance(entry.get("descending", False), bool):
            raise ValueError("a sort key is {key, descending}")
        out.append((entry["key"], entry.get("descending", False)))
    return out


def _sort(items, sorts):
    """Stable multi-key sort, first key first. Values of one key must be all strings or all finite numbers;
    items lacking the key (or null) come last whichever way it sorts."""
    items = list(items)
    for key, descending in reversed(sorts):
        present = [item[key] for item in items if item.get(key) is not None]
        if any(type(v) is bool or not (isinstance(v, str) or _number(v)) for v in present):
            raise ValueError("sort values must be strings or finite numbers: " + key)
        if len({isinstance(v, str) for v in present}) > 1:
            raise ValueError("mixed string and number sort values: " + key)
        have = sorted((i for i in items if i.get(key) is not None), key=lambda i: i[key], reverse=descending)
        items = have + [i for i in items if i.get(key) is None]
    return items


def _window(items, offset, limit):
    for name, value in (("offset", offset), ("limit", limit)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(name + " must be a non-negative integer")
    start = offset or 0
    return items[start:] if limit is None else items[start:start + limit]


def _group(items, key):
    if not isinstance(key, str) or not key:
        raise ValueError("group_by must be a field name")
    groups = []
    for item in items:
        value = item.get(key)
        if isinstance(value, (list, dict)):
            raise ValueError("group_by needs scalar values: " + key)
        group = next((g for g in groups if _equal(g["value"], value)), None)
        if group is None:
            group = {"value": value, "items": []}
            groups.append(group)
        group["items"].append(item)
    return groups


def filter_request(request):
    """Return selected original JSON objects in original order, without mutation
    (sorted, windowed or grouped when the request says so)."""
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    items = request.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("items must be an array of objects")
    query = request.get("query", "")
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    fields = request.get("text_fields", ["name"])
    if not isinstance(fields, list) or not fields or any(not isinstance(f, str) or not f for f in fields):
        raise ValueError("text_fields must be a nonempty array of field names")
    facets = request.get("facets", {})
    if not isinstance(facets, dict) or any(not isinstance(k, str) or isinstance(v, (list, dict)) for k, v in facets.items()):
        raise ValueError("facets must map field names to scalar JSON values")
    ranges = _ranges(request.get("ranges", {}))
    sorts = _sorts(request["sort"]) if "sort" in request else []
    needle = query.strip().lower()
    output = []
    for item in items:
        if needle:
            values = []
            for field in fields:
                value = item.get(field)
                values.extend(value if isinstance(value, list) else [value])
            if not any(needle in _text(value) for value in values):
                continue
        if any(key not in item or not (any(_equal(v, expected) for v in item[key]) if isinstance(item.get(key), list)
                    else _equal(item.get(key), expected))
               for key, expected in facets.items()):
            continue
        if any(not _number(item.get(key)) or not bounds.get("min", -math.inf) <= item[key] <= bounds.get("max", math.inf)
               for key, bounds in ranges.items()):
            continue
        output.append(item)
    if sorts:
        output = _sort(output, sorts)
    output = _window(output, request.get("offset"), request.get("limit"))
    return _group(output, request["group_by"]) if "group_by" in request else output


def _reject_non_json(value):
    raise ValueError("non-JSON number: " + value)


def main():
    try:
        request = json.load(sys.stdin, parse_constant=_reject_non_json)
        result = filter_request(request)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        return 0
    except (ValueError, TypeError, UnicodeError) as error:
        print("error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
