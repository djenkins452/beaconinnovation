"""YAML loading with a graceful fallback.

The release engine reads `release.yaml`. PyYAML is used when available (it is on
the system Python). If it is not installed, a small built-in parser handles the
simple subset that `release.yaml` uses: nested mappings (2-space indent),
scalars, and `- ` lists. This keeps the engine dependency-light and ensures it
never hard-fails just because PyYAML is missing.
"""

from __future__ import annotations

from typing import Any, Dict, List


def load_yaml(text: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        return data or {}
    except ImportError:
        return _fallback_parse(text)


# ---------------------------------------------------------------------------
# Minimal fallback parser (subset only)
# ---------------------------------------------------------------------------
def _fallback_parse(text: str) -> Dict[str, Any]:
    # (indent, content) for every significant line
    lines = []
    for raw in text.splitlines():
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    value, _ = _parse_block(lines, 0, 0)
    return value if isinstance(value, dict) else {}


def _parse_block(lines, index, indent):
    """Parse a mapping or list at the given indent; return (value, next_index)."""
    # list?
    if index < len(lines) and lines[index][1].startswith("- "):
        result: List[Any] = []
        while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
            item = lines[index][1][2:].strip()
            result.append(_scalar(item))
            index += 1
        return result, index

    # mapping
    result: Dict[str, Any] = {}
    while index < len(lines) and lines[index][0] == indent:
        cur_indent, content = lines[index]
        if content.startswith("- "):
            break
        if ":" not in content:
            index += 1
            continue
        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:
            result[key] = _scalar(rest)
            index += 1
        else:
            # nested block on following, more-indented lines
            if index + 1 < len(lines) and lines[index + 1][0] > cur_indent:
                child_indent = lines[index + 1][0]
                child, index = _parse_block(lines, index + 1, child_indent)
                result[key] = child
            else:
                result[key] = None
                index += 1
    return result, index


def _strip_comment(line: str) -> str:
    # drop full-line and inline comments; naive but fine for release.yaml
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1] == " ":
                return line[:i]
    return line


def _scalar(token: str) -> Any:
    if (token.startswith('"') and token.endswith('"')) or \
       (token.startswith("'") and token.endswith("'")):
        return token[1:-1]
    low = token.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token
