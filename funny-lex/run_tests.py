#!/usr/bin/env python3
"""
run_tests.py — тесты лексера, парсера (HW2), семантического анализа (HW3), IR и оптимизаций (HW4).

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
  HW4:
  9.  Точечные проверки оптимизаций на маленьких кусках IR: свёртка как в JVM (переполнение,
      деление к нулю), x / 0 и x / x не трогаем, DCE не удаляет то, что может упасть, CSE
      забывает выражение, когда операнд переписан, и т.д.
  10. tests/ir/*.funny — программы с ожидаемыми результатами (*.cases): IR ДО и ПОСЛЕ
      оптимизаций исполняется интерпретатором, оба результата равны ожидаемому
      (или оба — ошибка времени выполнения). IR до/после сверяется с эталоном *.ir.
  11. Дифференциальное тестирование: все корректные программы (tests/ir, types_good, good, примеры
      курса), случайные входы, разные наборы оптимизаций — результат до и после одинаков.
  12. Метрики и раскраска: инструкций и временных после оптимизаций не больше, чем до;
      раскраска графа конфликтов правильная (соседи — разных цветов) и проверена по живости;
      --O0 оставляет IR без изменений.
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
import random

from funny_ir import format_module, metrics, Copy, BinOp, UnOp, Load, IfGoto, Goto, Label, Return, \
    IRFunction, IRModule
from funny_irgen import generate
from funny_opt import optimize, PASSES
from funny_irinterp import run, parse_call, format_result
from funny_regalloc import allocate
from funny_cfg import build_cfg, liveness, live_after_each

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


# 9-12. HW4: IR И ОПТИМИЗАЦИИ

def opt_code(code, passes=None, params=(("x", "int"), ("y", "int")), temps=None, returns=(("r", "int"),)):
    """Оптимизировать кусок IR (список инструкций) и вернуть текст результата."""
    fn = IRFunction("f", list(params), list(returns), [], dict(temps or {}), code)
    module, _ = optimize(IRModule([fn]), passes)
    return "; ".join(str(i) for i in module.functions[0].code)


def test_ir_units():
    print("\n== 9. HW4, точечные проверки оптимизаций ==")
    t = {"t1": "int", "t2": "int", "t3": "int", "b": "bool"}
    cases = [
        ("свёртка: 2147483647 + 1 = -2147483648 (переполнение как в JVM)",
         [BinOp("r", "+", 2147483647, 1), Return(["r"])], "return -2147483648"),
        ("свёртка: -7 / 2 = -3 (деление к нулю, а не вниз)",
         [BinOp("r", "/", -7, 2), Return(["r"])], "return -3"),
        ("свёртка: MIN / -1 = MIN (переполнение)",
         [BinOp("r", "/", -2147483648, -1), Return(["r"])], "return -2147483648"),
        ("x / 0 не сворачивается и не удаляется (должно упасть во время выполнения)",
         [BinOp("t1", "/", "x", 0), Copy("r", 1), Return(["r"])], "t1 := x / 0; return 1"),
        ("x / x не упрощается до 1 (при x == 0 — ошибка)",
         [BinOp("r", "/", "x", "x"), Return(["r"])], "r := x / x; return r"),
        ("0 * x -> 0, x - x -> 0, x * 1 -> x",
         [BinOp("t1", "*", 0, "x"), BinOp("t2", "-", "y", "y"), BinOp("t3", "*", "x", 1),
          BinOp("t1", "+", "t1", "t2"), BinOp("r", "+", "t1", "t3"), Return(["r"])], "return x"),
        ("x * 2 -> x + x",
         [BinOp("r", "*", "x", 2), Return(["r"])], "r := x + x; return r"),
        ("CSE: a + b и b + a — одно выражение",
         [BinOp("t1", "+", "x", "y"), BinOp("t2", "+", "y", "x"), BinOp("r", "*", "t1", "t2"), Return(["r"])],
         "t1 := x + y; r := t1 * t1; return r"),
        ("CSE: после записи в операнд выражение пересчитывается",
         [BinOp("t1", "+", "x", "y"), Copy("x", 5), BinOp("t2", "+", "x", "y"), BinOp("r", "*", "t1", "t2"),
          Return(["r"])], "t1 := x + y; t2 := 5 + y; r := t1 * t2; return r"),
        ("DCE: load не удаляется (выход за границы), неиспользуемая арифметика удаляется",
         [Load("t1", "a", "x"), BinOp("t2", "+", "x", 1), Copy("r", "x"), Return(["r"])],
         "t1 := load a[x]; return x"),
        ("if true goto L -> goto L; недостижимый код удаляется",
         [BinOp("b", "<", 1, 2), IfGoto("b", "L1"), Copy("r", 0), Goto("L2"), Label("L1"), Copy("r", 1),
          Label("L2"), Return(["r"])], "return 1"),
        ("константы не переходят через границу блока (локальный анализ)",
         [Copy("t1", 1), Label("L1"), BinOp("r", "+", "t1", 1), BinOp("b", "<", "r", "y"), IfGoto("b", "L1"),
          Return(["r"])], "t1 := 1; L1:; r := t1 + 1; b := r < y; if b goto L1; return r"),
    ]
    for name, code, expected in cases:
        got = opt_code(code, temps=t, params=(("x", "int"), ("y", "int"), ("a", "int[]")))
        check(got == expected, name, f"    ожидалось: {expected}\n    получено:  {got}")
    got = opt_code([BinOp("t1", "*", 0, "x"), BinOp("r", "+", "t1", 0), Return(["r"])],
                   passes={"constprop"}, temps=t)
    check(got == "t1 := 0 * x; r := t1 + 0; return r",
          "--opt=constprop: алгебра выключена, 0 * x и + 0 остаются", f"    получено: {got}")


def read_cases(path):
    """Строки 'f(1, [2]) -> 3, 4' (или '-> ошибка'); пустые и с # пропускаем."""
    result = []
    for line in read(path).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            call, expected = [x.strip() for x in line.split("->", 1)]
            result.append((call, expected))
    return result


def test_ir_programs():
    print("\n== 10. HW4, tests/ir: результат до и после оптимизаций равен ожидаемому, IR совпадает с эталоном ==")
    for path in sorted(glob.glob(os.path.join(HERE, "tests", "ir", "*.funny"))):
        name = os.path.relpath(path, HERE)
        module, errors = analyze(read(path))
        if errors:
            check(False, name, "\n".join(f"    неожиданная ошибка {e}" for e in errors))
            continue
        before = generate(module)
        after, reports = optimize(before)
        problems = []
        for call, expected in read_cases(path[:-len(".funny")] + ".cases"):
            fname, args = parse_call(call)
            r1, r2 = format_result(run(before, fname, args)), format_result(run(after, fname, args))
            ok = r1 == r2 and (r1 == expected or (expected == "ошибка" and r1.startswith("ошибка")))
            if not ok:
                problems.append(f"    {call}: ожидалось {expected}; до: {r1}; после: {r2}")
        check(not problems, f"{name}: все входы из .cases", "\n".join(problems))
        got = "# до оптимизаций\n" + format_module(before) + "\n# после оптимизаций\n" + format_module(after)
        snapshot = path[:-len(".funny")] + ".ir"
        if UPDATE or not os.path.exists(snapshot):
            write(snapshot, got)
            print(f"[SAVE] {os.path.relpath(snapshot, HERE)}")
        else:
            expected = read(snapshot)
            check(got == expected, f"{name}: IR до/после совпадает с эталоном .ir", diff(expected, got))


def all_good_programs():
    """Все программы без ошибок: (имя, IR без оптимизаций)."""
    paths = (sorted(glob.glob(os.path.join(HERE, "tests", "ir", "*.funny")))
             + sorted(glob.glob(os.path.join(HERE, "tests", "types_good", "*.funny")))
             + sorted(glob.glob(os.path.join(HERE, "tests", "good", "*.funny")))
             + sorted(glob.glob(os.path.join(HERE, "tests", "course", "*", "good_*.funny"))))
    for path in paths:
        module, errors = analyze(read(path))
        if not errors:
            yield os.path.relpath(path, HERE), generate(module)


def random_value(rng, type_):
    if type_ == "int[]":
        return tuple(rng.randint(-6, 6) for _ in range(rng.randint(0, 5)))
    return rng.choice([0, 1, -1, 2, 3, 7, -8, 10, 2147483647, -2147483648, rng.randint(-50, 50)])


def test_differential():
    print("\n== 11. HW4, дифференциальное тестирование: до и после оптимизаций — одинаковый результат ==")
    rng = random.Random(4)
    pass_sets = [list(PASSES)] + [[p] for p in PASSES] + [[q for q in PASSES if q != p] for p in PASSES]
    for name, before in all_good_programs():
        runs, problems = 0, []
        for passes in pass_sets:
            after, _ = optimize(before, passes)
            for fn in before.functions:
                for _ in range(8):
                    args = [random_value(rng, t) for _, t in fn.params]
                    r1, r2 = run(before, fn.name, args, 20000), run(after, fn.name, args, 20000)
                    runs += 1
                    if r1 != r2 and r1[0] != "timeout":
                        problems.append(f"    {fn.name}{args} с {','.join(passes)}: до {r1}, после {r2}")
        check(not problems, f"{name}: {runs} запусков", "\n".join(problems[:5]))


def coloring_ok_by_liveness(fn, graph):
    """Независимая проверка: две переменные, живые одновременно (и обе — узлы), разного цвета."""
    cfg = build_cfg(fn)
    liveness(cfg)
    for b in cfg.blocks:
        for ins, live in zip(b.instrs, live_after_each(b)):
            for d in ins.defs():
                for v in live:
                    if d != v and d in graph.colors and v in graph.colors and graph.colors[d] == graph.colors[v]:
                        if not (isinstance(ins, Copy) and ins.src == v):
                            return f"{d} и {v} живы одновременно после «{ins}», но оба цвета {graph.colors[d]}"
    return None


def test_metrics_and_coloring():
    print("\n== 12. HW4, метрики и раскраска ==")
    total = [0, 0, 0, 0]
    for name, before in all_good_programs():
        after, reports = optimize(before)
        problems = []
        for fn in after.functions:
            r = reports[fn.name]
            if r["after"]["instructions"] > r["before"]["instructions"] or r["after"]["temps"] > r["before"]["temps"]:
                problems.append(f"    {fn.name}: стало больше: {r['before']} -> {r['after']}")
            for color_all in (False, True):
                g = allocate(fn, color_all)
                if not g.is_valid():
                    problems.append(f"    {fn.name}: соседи одного цвета")
                bad = coloring_ok_by_liveness(fn, g)
                if bad:
                    problems.append(f"    {fn.name}: {bad}")
            total = [total[0] + r["before"]["instructions"], total[1] + r["after"]["instructions"],
                     total[2] + r["before"]["temps"], total[3] + r["after"]["temps"]]
        unopt, _ = optimize(before, [])
        if format_module(unopt) != format_module(before):
            problems.append("    --O0 изменил IR")
        check(not problems, f"{name}: метрики не хуже, раскраска правильная, --O0 ничего не меняет",
              "\n".join(problems))
    print(f"       всего по программам: инструкций {total[0]} -> {total[1]}, временных {total[2]} -> {total[3]}")


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
    test_ir_units()
    test_ir_programs()
    test_differential()
    test_metrics_and_coloring()
    print(f"\nИтог: провалено {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
