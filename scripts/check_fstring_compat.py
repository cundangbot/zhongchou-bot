"""Check Python sources for f-string expressions containing backslashes.

Python 3.11 and older reject a backslash inside the expression portion of an
f-string. Keep escaped newlines in a variable outside the ``{...}`` expression.
This checker intentionally avoids embedding an invalid f-string example in its
own source so simple text searches do not report a false positive.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


_INLINE_FSTRING = re.compile(r"(?:^|[^A-Za-z0-9_])(?:f|fr|rf)(['\"])(.*?)\1")
_EXPRESSION = re.compile(r"\{([^{}]*)\}")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    problems: list[tuple[Path, int, str]] = []

    for path in root.rglob("*.py"):
        if any(part in {".venv", "venv", "__pycache__"} for part in path.parts):
            continue

        source = _read(path)
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            problems.append((path, exc.lineno or 0, f"SyntaxError: {exc.msg}"))
            continue

        # Conservative source scan. It catches the historically problematic
        # one-line pattern without relying on Python 3.12+ f-string AST rules.
        for line_no, line in enumerate(source.splitlines(), 1):
            for match in _INLINE_FSTRING.finditer(line):
                body = match.group(2)
                for expression in _EXPRESSION.findall(body):
                    if "\\" in expression:
                        problems.append((path, line_no, expression.strip()))

    if problems:
        print("发现可能不兼容 Python 3.11 的 f-string 表达式：")
        for path, line, detail in problems:
            print(f"- {path}:{line}: {detail}")
        return 1

    print("OK：未发现 f-string 表达式内部反斜杠。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
