#!/usr/bin/env python3
"""
funny.py — командная строка для лексера и парсера Funny (HW2).

    python funny.py file.funny             AST в виде дерева
    python funny.py file.funny --json      AST в JSON
    python funny.py file.funny --tokens    поток токенов с позициями

Ошибки печатаются в stderr в виде  файл:строка:столбец: ошибка: текст
(VS Code и другие редакторы умеют переходить по таким ссылкам),
под каждой — строка исходника и ^ под местом ошибки.
Код выхода: 0 — ошибок нет, 1 — есть ошибки.
"""
import json
import sys

from funny_ast import dump, to_json
from funny_lexer import tokenize
from funny_parser import parse


def print_error(path, source_lines, err):
    print(f"{path}:{err.line}:{err.col}: ошибка: {err.message}", file=sys.stderr)
    if err.line <= len(source_lines):
        line = source_lines[err.line - 1].replace("\t", " ")   # табуляция = 1 столбец, как в лексере
        print("    " + line, file=sys.stderr)
        print("    " + " " * (err.col - 1) + "^", file=sys.stderr)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    path = args[0]

    # Русские сообщения должны печататься и в консоли Windows, и в файл
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    with open(path, encoding="utf-8-sig") as f:    # utf-8-sig: убрать BOM, если файл из Блокнота
        text = f.read()

    if "--tokens" in flags:
        tokens, errors = tokenize(text)
        for t in tokens:
            print(f"{t.line:>3}:{t.col:<3} {t.kind:<13} {t.text}")
    else:
        module, errors = parse(text)
        if not errors:
            if "--json" in flags:
                print(json.dumps(to_json(module), ensure_ascii=False, indent=2))
            else:
                print(dump(module))

    source_lines = text.splitlines()
    for err in errors:
        print_error(path, source_lines, err)
    if errors:
        print(f"ошибок: {len(errors)}", file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
