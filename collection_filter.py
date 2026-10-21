#!/usr/bin/env python3
"""Portable collection filter: JSON on stdin -> JSON on stdout (stdlib only).

Equivalent public data contract to js/collection-cli.cjs; domain-specific
browser filters and callbacks remain in js/collection.js.
"""
from __future__ import annotations

import json
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


def filter_request(request):
    """Return selected original JSON objects in original order, without mutation."""
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
        output.append(item)
    return output


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
