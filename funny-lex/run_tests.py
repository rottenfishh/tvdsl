#!/usr/bin/env python3
"""
run_tests.py — тесты лексера, парсера (HW2) и семантического анализа (HW3).

    python run_tests.py             прогнать все тесты
    python run_tests.py --update    перезаписать эталоны (.ast, .typed, .err) текущим выводом
                                    (только после того, как проверили вывод глазами!)

Что проверяется:
  1. Лексер: токены с позициями и лексические ошибки на коротких строках.
  2. tests/good/*.funny — программа разбирается без ошибок, AST совпадает с эталоном *.ast.
  3. tests/bad/*.funny  — список ошибок совпадает с эталоном *.err (строка:столбец: текст).
  4. tests/course/      — примеры из репозитория курса: good_* разбираются без ошибок
                          (кроме step12 с не-ASCII "→"), синтаксически неверные bad_* дают ошибку. Остальные bad_* синтаксически
                          правильны (там ошибки типов и имён — это HW3), они тоже должны разбираться.
  5. Устойчивость: из каждой хорошей программы удаляем по одному токену и обрезаем её
     после каждого токена — парсер и семантический анализ должны ЗАВЕРШИТЬСЯ
     (не упасть и не зависнуть). Так проверяется, что режим паники не зацикливается,
     а анализатор не падает на необычных, но синтаксически правильных программах.
  HW3:
  6. tests/types_good/*.funny — нет ни синтаксических, ни семантических ошибок,
     аннотированный AST (с типами выражений и выведенными локальными) совпадает с *.typed.
  7. tests/types_bad/*.funny  — синтаксис правильный, семантические ошибки совпадают с *.err.
  8. tests/course/ — семантика примеров курса: good_* без ошибок, bad_* с ошибкой;
     все сообщения сверяются с эталоном tests/course_semantic.err.
"""
import difflib
import glob
import os
import sys
import threading

from funny_ast import dump
from funny_lexer import tokenize
from funny_parser import parse
from funny_semantic import analyze, check as semantic_check

HERE = os.path.dirname(os.path.abspath(__file__))
UPDATE = "--update" in sys.argv

failed = 0


def check(ok, name, details=""):
    """Напечатать PASS/FAIL и посчитать провалы."""
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failed += 1
        if details:
            print(details)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def diff(expected, got):
    lines = difflib.unified_diff(expected.splitlines(), got.splitlines(), "ожидалось", "получено", lineterm="")
    return "\n".join("    " + line for line in lines)


def parse_with_timeout(text, seconds=5.0):
    """analyze(text) (парсер + семантика) в отдельном потоке.
    Ответ: ("ok", (module, errors)), ("crash", исключение) или ("hang", None)."""
    result = {}

    def work():
        try:
            result["value"] = analyze(text)
        except Exception as e:                  # любое падение парсера — это провал теста
            result["crash"] = e

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        return "hang", None
    if "crash" in result:
        return "crash", result["crash"]
    return "ok", result["value"]


# 1. ЛЕКСЕР
# (текст, ожидаемые токены "ВИД@строка:столбец" через пробел, ожидаемые ошибки)

LEXER_TESTS = [
    ("r = 1;", "IDENT@1:1 ASSIGN@1:3 INT@1:5 SEMI@1:6 EOF@1:7", []),
    ("a\n  b", "IDENT@1:1 IDENT@2:3 EOF@2:4", []),
    ("a\r\nb", "IDENT@1:1 IDENT@2:1 EOF@2:2", []),
    ("x // комментарий\ny", "IDENT@1:1 IDENT@2:1 EOF@2:2", []),
    ("a:int[]", "IDENT@1:1 COLON@1:2 KW_INT@1:3 LBRACKET@1:6 RBRACKET@1:7 EOF@1:8", []),
    ("a->b", "IDENT@1:1 ARROW@1:2 IDENT@1:4 EOF@1:5", []),
    ("a→b", "IDENT@1:1 IDENT@1:3 EOF@1:4", ["1:2: недопустимый символ: '→'"]),   # не-ASCII; 3 байта, но 1 столбец
    ("f(x:int) => true", "IDENT@1:1 LPAREN@1:2 IDENT@1:3 COLON@1:4 KW_INT@1:5 RPAREN@1:8 "
                         "DARROW@1:10 KW_TRUE@1:13 EOF@1:17", []),
    ("", "EOF@1:1", []),
    ("x = 01;", "IDENT@1:1 ASSIGN@1:3 INT@1:5 SEMI@1:7 EOF@1:8", ["1:5: число с ведущим нулём: '01'"]),
    ("a @ b", "IDENT@1:1 IDENT@1:5 EOF@1:6", ["1:3: недопустимый символ: '@'"]),
    ("привет мир", "EOF@1:11", ["1:1: недопустимый символ: 'привет'", "1:8: недопустимый символ: 'мир'"]),
    ("a!b", "IDENT@1:1 IDENT@1:3 EOF@1:4", ["1:2: недопустимый символ: '!'"]),
]


def test_lexer():
    print("== 1. Лексер ==")
    for text, expected_tokens, expected_errors in LEXER_TESTS:
        tokens, errors = tokenize(text)
        got_tokens = " ".join(f"{t.kind}@{t.line}:{t.col}" for t in tokens)
        got_errors = [str(e) for e in errors]
        ok = got_tokens == expected_tokens and got_errors == expected_errors
        check(ok, f"lex {text!r}",
              f"    ожидалось: {expected_tokens} {expected_errors}\n    получено:  {got_tokens} {got_errors}")


# 2. ПОЗИТИВНЫЕ ПРОГРАММЫ: AST совпадает с эталоном

def test_good():
    print("\n== 2. Позитивные программы (tests/good): сравнение AST с эталоном ==")
    for path in sorted(glob.glob(os.path.join(HERE, "tests", "good", "*.funny"))):
        name = os.path.relpath(path, HERE)
        module, errors = parse(read(path))
        if errors:
            check(False, name, "\n".join(f"    неожиданная ошибка {e}" for e in errors))
            continue
        got = dump(module) + "\n"
        snapshot = path[:-len(".funny")] + ".ast"
        if UPDATE or not os.path.exists(snapshot):
            write(snapshot, got)
            print(f"[SAVE] {os.path.relpath(snapshot, HERE)}")
            continue
        expected = read(snapshot)
        check(got == expected, name, diff(expected, got))


# 3. НЕГАТИВНЫЕ ПРОГРАММЫ: ошибки совпадают с эталоном

def test_bad():
    print("\n== 3. Негативные программы (tests/bad): сравнение ошибок с эталоном ==")
    for path in sorted(glob.glob(os.path.join(HERE, "tests", "bad", "*.funny"))):
        name = os.path.relpath(path, HERE)
        status, value = parse_with_timeout(read(path))
        if status != "ok":
            check(False, name, f"    парсер {'завис' if status == 'hang' else 'упал: ' + repr(value)}")
            continue
        module, errors = value
        got = "".join(str(e) + "\n" for e in errors)
        expected_path = path[:-len(".funny")] + ".err"
        if UPDATE or not os.path.exists(expected_path):
            write(expected_path, got)
            print(f"[SAVE] {os.path.relpath(expected_path, HERE)}")
            continue
        expected = read(expected_path)
        check(errors and got == expected, name, diff(expected, got) or "    ошибок нет, а должны быть")


# 4. ПРИМЕРЫ КУРСА

# Эти примеры из курса дают ошибку на этапе лексера/парсера. Остальные bad_* — семантические (HW3).
# good_formulas_sorted.funny пишет импликацию символом "→", а алфавит Funny — ASCII (в грамматике "->"),
# поэтому этот пример даёт лексическую ошибку — расхождение примера со спецификацией, см. grammar.txt.
COURSE_SYNTAX_ERRORS = {"bad_missing_semicolon.funny", "bad_missing_paren.funny", "good_formulas_sorted.funny"}


def test_course():
    print("\n== 4. Примеры из репозитория курса (tests/course) ==")
    paths = sorted(glob.glob(os.path.join(HERE, "tests", "course", "*", "*.funny")))
    for path in paths:
        name = os.path.relpath(path, HERE)
        module, errors = parse(read(path))
        if os.path.basename(path) in COURSE_SYNTAX_ERRORS:
            check(len(errors) > 0, f"{name}  (должна быть ошибка)")
        else:
            check(not errors, name, "\n".join(f"    неожиданная ошибка {e}" for e in errors))


# 5. УСТОЙЧИВОСТЬ: парсер всегда завершается

def test_robustness():
    print("\n== 5. Устойчивость: удаляем любой токен / обрезаем программу — парсер и семантика завершаются ==")
    paths = sorted(glob.glob(os.path.join(HERE, "tests", "good", "*.funny")))
    paths += sorted(glob.glob(os.path.join(HERE, "tests", "types_good", "*.funny")))
    paths += [p for p in sorted(glob.glob(os.path.join(HERE, "tests", "course", "*", "good_*.funny")))
              if os.path.basename(p) not in COURSE_SYNTAX_ERRORS]
    variants = 0
    problems = []
    for path in paths:
        tokens, _ = tokenize(read(path))
        words = [t.text for t in tokens if t.kind != "EOF"]
        cases = []
        for i in range(len(words)):
            cases.append(" ".join(words[:i] + words[i + 1:]))    # без i-го токена
            cases.append(" ".join(words[:i]))                    # только первые i токенов
        for text in cases:
            variants += 1
            status, value = parse_with_timeout(text)
            if status != "ok":
                problems.append(f"    {status}: {os.path.relpath(path, HERE)}: {text[:80]!r}")
    check(not problems, f"{variants} испорченных вариантов {len(paths)} программ", "\n".join(problems[:10]))

    # Глубокая рекурсия — в главном потоке: у дополнительных потоков стек бывает меньше.
    deep = "f() returns r:int { r = " + "(" * 3000 + "1" + ")" * 3000 + "; }"
    module, errors = parse(deep)
    check(len(errors) == 1, "3000 вложенных скобок: одна понятная ошибка, а не падение",
          "\n".join(f"    {e}" for e in errors))


# 6-8. HW3: СЕМАНТИКА

def test_types_good():
    print("\n== 6. HW3, позитивные (tests/types_good): нет ошибок, аннотированный AST совпадает с эталоном ==")
    for path in sorted(glob.glob(os.path.join(HERE, "tests", "types_good", "*.funny"))):
        name = os.path.relpath(path, HERE)
        module, errors = analyze(read(path))
        if errors:
            check(False, name, "\n".join(f"    неожиданная ошибка {e}" for e in errors))
            continue
        got = dump(module) + "\n"
        snapshot = path[:-len(".funny")] + ".typed"
        if UPDATE or not os.path.exists(snapshot):
            write(snapshot, got)
            print(f"[SAVE] {os.path.relpath(snapshot, HERE)}")
            continue
        expected = read(snapshot)
        check(got == expected, name, diff(expected, got))


def test_types_bad():
    print("\n== 7. HW3, негативные (tests/types_bad): семантические ошибки совпадают с эталоном ==")
    for path in sorted(glob.glob(os.path.join(HERE, "tests", "types_bad", "*.funny"))):
        name = os.path.relpath(path, HERE)
        module, errors = parse(read(path))
        if errors:                                 # здесь синтаксис должен быть правильным
            check(False, name, "\n".join(f"    синтаксическая ошибка {e}" for e in errors))
            continue
        errors = semantic_check(module)
        got = "".join(str(e) + "\n" for e in errors)
        expected_path = path[:-len(".funny")] + ".err"
        if UPDATE or not os.path.exists(expected_path):
            write(expected_path, got)
            print(f"[SAVE] {os.path.relpath(expected_path, HERE)}")
            continue
        expected = read(expected_path)
        check(errors and got == expected, name, diff(expected, got) or "    ошибок нет, а должны быть")


# good_while_nested.funny из курса пишет в параметр (n = n - 1), а funny.ru.md это запрещает
# («параметры ... доступны только для чтения»; соседний bad_modify_param проверяет ровно это).
# Поэтому семантический анализ правильно находит в нём ошибку — расхождение примера со спецификацией.
COURSE_SEMANTIC_ERRORS = {"good_while_nested.funny"}


def test_course_semantic():
    print("\n== 8. HW3, примеры курса: good_* без семантических ошибок, bad_* с ошибкой ==")
    lines = []
    for path in sorted(glob.glob(os.path.join(HERE, "tests", "course", "*", "*.funny"))):
        base = os.path.basename(path)
        if base in COURSE_SYNTAX_ERRORS:
            continue                               # синтаксические ошибки — это группа 4
        rel = os.path.relpath(path, HERE).replace(os.sep, "/")
        module, errors = analyze(read(path))
        lines += [f"{rel}:{e}" for e in errors]
        if base.startswith("good_") and base not in COURSE_SEMANTIC_ERRORS:
            check(not errors, rel, "\n".join(f"    неожиданная ошибка {e}" for e in errors))
        else:
            check(len(errors) > 0, f"{rel}  (должна быть ошибка: {errors[0].message if errors else '—'})")
    got = "".join(line + "\n" for line in lines)
    snapshot = os.path.join(HERE, "tests", "course_semantic.err")
    if UPDATE or not os.path.exists(snapshot):
        write(snapshot, got)
        print(f"[SAVE] {os.path.relpath(snapshot, HERE)}")
        return
    expected = read(snapshot)
    check(got == expected, "тексты и позиции всех сообщений совпадают с tests/course_semantic.err", diff(expected, got))


def main():
    sys.stdout.reconfigure(encoding="utf-8")       # символ → в выводе: иначе Windows-кодировка cp1251 падает
    test_lexer()
    test_good()
    test_bad()
    test_course()
    test_robustness()
    test_types_good()
    test_types_bad()
    test_course_semantic()
    print(f"\nИтог: провалено {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
