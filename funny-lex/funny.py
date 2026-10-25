#!/usr/bin/env python3
"""
funny.py — командная строка для лексера, парсера (HW2) и семантического анализа (HW3).

    python funny.py file.funny                 аннотированный AST (у выражений — типы)
    python funny.py file.funny --json          аннотированный AST в JSON
    python funny.py file.funny --symbols       таблица символов: функции, параметры, локальные и их типы
    python funny.py file.funny --parse-only    AST без семантического анализа (как в HW2)
    python funny.py file.funny --tokens        поток токенов с позициями

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
from funny_semantic import check


def print_error(path, source_lines, err):
    print(f"{path}:{err.line}:{err.col}: ошибка: {err.message}", file=sys.stderr)
    if err.line <= len(source_lines):
        line = source_lines[err.line - 1].replace("\t", " ")   # табуляция = 1 столбец, как в лексере
        print("    " + line, file=sys.stderr)
        print("    " + " " * (err.col - 1) + "^", file=sys.stderr)


def print_symbols(module):
    """Таблица символов модуля: для каждой функции — параметры, результаты, локальные с типами."""
    def names(defs):
        return ", ".join(f"{v.name}: {v.type}" for v in defs) or "—"
    for item in module.items:
        if hasattr(item, "returns"):
            print(f"функция {item.name}  @{item.pos[0]}:{item.pos[1]}")
            print(f"    параметры:    {names(item.params)}")
            print(f"    возвращает:   {names(item.returns)}")
            print(f"    локальные:    {names(item.locals or [])}")
        else:
            print(f"формула {item.name}  @{item.pos[0]}:{item.pos[1]}")
            print(f"    параметры:    {names(item.params)}")


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
        if not errors:                             # синтаксис в порядке — печатаем дерево
            if "--parse-only" not in flags:
                errors = check(module)             # HW3: имена и типы; дерево получает типы
            if "--json" in flags:
                print(json.dumps(to_json(module), ensure_ascii=False, indent=2))
            elif "--symbols" in flags:
                print_symbols(module)
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
