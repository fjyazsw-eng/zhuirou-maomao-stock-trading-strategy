from __future__ import annotations

import ast
import json
import re
from typing import Any, Iterable

__all__ = ["safe_load", "load", "safe_dump", "dump"]


_NULLS = {"null", "Null", "NULL", "~", ""}
_BOOLS = {"true": True, "false": False, "True": True, "False": False}


def safe_load(stream: Any) -> Any:
    if hasattr(stream, "read"):
        text = stream.read()
    else:
        text = stream
    if text is None:
        return None
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    if not isinstance(text, str):
        text = str(text)

    lines = _prepare_lines(text)
    if not lines:
        return None

    value, index = _parse_block(lines, 0, _indent(lines[0]))
    while index < len(lines):
        if lines[index].strip():
            raise ValueError(f"Unexpected trailing content near line {index + 1}")
        index += 1
    return value


def load(stream: Any) -> Any:
    return safe_load(stream)


def safe_dump(data: Any, stream: Any | None = None, **kwargs: Any) -> str | None:
    text = json.dumps(data, ensure_ascii=False, indent=kwargs.get("indent", 2))
    if stream is None:
        return text
    stream.write(text)
    return None


def dump(data: Any, stream: Any | None = None, **kwargs: Any) -> str | None:
    return safe_dump(data, stream=stream, **kwargs)


def _prepare_lines(text: str) -> list[str]:
    text = text.replace("\ufeff", "")
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = _strip_inline_comment(raw.rstrip())
        if not stripped.strip():
            continue
        lines.append(stripped.rstrip())
    return lines


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    depth = 0
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch in "[{(":
                depth += 1
            elif ch in "]})" and depth > 0:
                depth -= 1
            elif ch == "#" and depth == 0 and (idx == 0 or line[idx - 1].isspace()):
                return line[:idx].rstrip()
    return line


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_block(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return None, index

    first = lines[index]
    if _indent(first) != indent:
        raise ValueError(f"Invalid indentation near line {index + 1}")

    if first.lstrip().startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(lines: list[str], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        line_indent = _indent(line)
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"Unexpected indentation near line {index + 1}")

        content = line[indent:]
        if content.startswith("- "):
            break

        key, rest = _split_key_value(content)
        if key is None:
            raise ValueError(f"Invalid mapping entry near line {index + 1}")

        if rest:
            result[key] = _parse_value(rest)
            index += 1
            continue

        index += 1
        if index < len(lines) and _indent(lines[index]) > indent:
            child, index = _parse_block(lines, index, _indent(lines[index]))
            result[key] = child
        else:
            result[key] = None

    return result, index


def _parse_list(lines: list[str], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line = lines[index]
        line_indent = _indent(line)
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"Unexpected indentation near line {index + 1}")

        content = line[indent:]
        if not content.startswith("- "):
            break

        item_text = content[2:].strip()
        index += 1

        if not item_text:
            if index < len(lines) and _indent(lines[index]) > indent:
                child, index = _parse_block(lines, index, _indent(lines[index]))
                result.append(child)
            else:
                result.append(None)
            continue

        item = _parse_inline_item(item_text)
        if index < len(lines) and _indent(lines[index]) > indent:
            child, index = _parse_block(lines, index, _indent(lines[index]))
            if isinstance(item, dict) and isinstance(child, dict):
                item.update(child)
            elif item is None:
                item = child
        result.append(item)

    return result, index


def _parse_inline_item(text: str) -> Any:
    if _looks_like_inline_map(text):
        return _parse_inline_map(text)
    return _parse_value(text)


def _looks_like_inline_map(text: str) -> bool:
    return ":" in text and not text.startswith(("{", "[", '"', "'"))


def _parse_inline_map(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for part in _split_top_level(text, ","):
        key, value = _split_key_value(part)
        if key is None:
            raise ValueError(f"Invalid inline mapping entry: {part!r}")
        result[key] = _parse_value(value)
    return result


def _parse_value(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text in _NULLS:
        return None
    if text in _BOOLS:
        return _BOOLS[text]
    if text[0] in "[{" and text[-1] in "]}":
        return _parse_flow_collection(text)
    if (text[0] == text[-1]) and text[0] in {'"', "'"}:
        return ast.literal_eval(text)
    if _is_number(text):
        return int(text) if re.fullmatch(r"[+-]?\d+", text) else float(text)
    return text


def _parse_flow_collection(text: str) -> Any:
    inner = text[1:-1].strip()
    if text.startswith("["):
        if not inner:
            return []
        return [_parse_value(part) for part in _split_top_level(inner, ",")]

    if not inner:
        return {}
    result: dict[str, Any] = {}
    for part in _split_top_level(inner, ","):
        key, value = _split_key_value(part)
        if key is None:
            raise ValueError(f"Invalid flow mapping entry: {part!r}")
        result[key] = _parse_value(value)
    return result


def _split_key_value(text: str) -> tuple[str | None, str]:
    idx = _find_top_level(text, ":")
    if idx < 0:
        return None, ""
    key = text[:idx].strip()
    value = text[idx + 1 :].strip()
    if (key[0] == key[-1]) and key[0] in {'"', "'"}:
        key = ast.literal_eval(key)
    return key, value


def _split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_single = False
    in_double = False
    for idx, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch in "[{(":
                depth += 1
            elif ch in "]})" and depth > 0:
                depth -= 1
            elif ch == separator and depth == 0:
                parts.append(text[start:idx].strip())
                start = idx + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return [part for part in parts if part]


def _find_top_level(text: str, needle: str) -> int:
    depth = 0
    in_single = False
    in_double = False
    for idx, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch in "[{(":
                depth += 1
            elif ch in "]})" and depth > 0:
                depth -= 1
            elif ch == needle and depth == 0:
                return idx
    return -1


def _is_number(text: str) -> bool:
    return bool(re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)", text))
