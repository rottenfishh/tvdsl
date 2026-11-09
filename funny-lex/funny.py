#!/usr/bin/env python3
"""
funny.py — командная строка: лексер, парсер (HW2), семантический анализ (HW3), IR и оптимизации (HW4).

    python funny.py file.funny                 аннотированный AST (у выражений — типы)
    python funny.py file.funny --json          аннотированный AST в JSON
    python funny.py file.funny --symbols       таблица символов: функции, параметры, локальные и их типы
    python funny.py file.funny --parse-only    AST без семантического анализа 
    python funny.py file.funny --tokens        поток токенов с позициями

HW4 — трёхадресный код (IR), CFG, оптимизации, граф конфликтов:
    --ir                     IR до и после оптимизаций + метрики
    --ir-json                IR после оптимизаций в JSON (с --O0 — без оптимизаций)
    --O0                     не оптимизировать
    --opt=constprop,dce      включить ТОЛЬКО перечисленные оптимизации
    --disable=cse,algebra    выключить перечисленные (остальные включены)
                             имена: constprop algebra copies cse dce unreachable
    --config=opt.json        то же из файла: {"optimizations": [...], "regs": 4, "color_all": false}
    --cfg                    базовые блоки, рёбра и живые переменные (in/out)
    --cfg-dot                CFG в формате Graphviz DOT
    --interference           граф конфликтов временных и жадная раскраска
    --interference-dot       граф конфликтов в DOT (цвет узла = номер регистра)
    --regs=K                 K регистров: узлы с цветом >= K — сброс (spill)
    --color-all              красить не только временные, но и переменные программы
    --run="f(1, [2, 3])"     выполнить функцию на IR до и после оптимизаций, сравнить результаты
    --out-dir=DIR            записать IR, текст CFG/конфликтов и метрики в папку DIR

Ошибки печатаются в stderr в виде  файл:строка:столбец: ошибка: текст
(VS Code и другие редакторы умеют переходить по таким ссылкам),
под каждой — строка исходника и ^ под местом ошибки.
Код выхода: 0 — ошибок нет, 1 — есть ошибки (или результаты --run до/после различаются).
"""
import json
import os
import sys

from funny_ast import dump, to_json
from funny_lexer import tokenize
from funny_parser import parse
from funny_semantic import check

HW4_FLAGS = ("--ir", "--ir-json", "--cfg", "--cfg-dot", "--interference", "--interference-dot",
             "--run", "--out-dir")
HW4_SETTINGS = ("--O0", "--opt", "--disable", "--config", "--regs", "--color-all")   # без вывода -> --ir


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


# ---------- HW4 ----------

def flag_value(flags, name):
    """--name=value -> value; нет флага -> None."""
    for f in flags:
        if f.startswith(name + "="):
            return f[len(name) + 1:]
    return None


def has_flag(flags, name):
    return name in flags or flag_value(flags, name) is not None


def hw4_settings(flags):
    """Какие оптимизации включены, число регистров, красить ли всё. Ошибка в флагах -> SystemExit."""
    from funny_opt import PASSES, parse_pass_list
    enabled, regs, color_all = set(PASSES), None, "--color-all" in flags
    try:
        config = flag_value(flags, "--config")
        if config:
            with open(config, encoding="utf-8") as f:
                cfg = json.load(f)
            if "optimizations" in cfg:
                enabled = parse_pass_list(",".join(cfg["optimizations"]))
            regs = cfg.get("regs", regs)
            color_all = cfg.get("color_all", color_all)
        if flag_value(flags, "--opt") is not None:
            enabled = parse_pass_list(flag_value(flags, "--opt"))
        if flag_value(flags, "--disable") is not None:
            enabled -= parse_pass_list(flag_value(flags, "--disable"))
        if "--O0" in flags:
            enabled = set()
        if flag_value(flags, "--regs") is not None:
            regs = int(flag_value(flags, "--regs"))
    except (ValueError, OSError) as e:
        sys.exit(f"ошибка в параметрах: {e}")
    return [p for p in PASSES if p in enabled], regs, color_all


def metrics_table(reports, graphs):
    rows = [("функция", "инструкций до -> после", "временных до -> после", "цветов")]
    tb = ta = vb = va = 0
    for name, r in reports.items():
        b, a = r["before"], r["after"]
        rows.append((name, f"{b['instructions']} -> {a['instructions']}",
                     f"{b['temps']} -> {a['temps']}", str(graphs[name].num_colors)))
        tb, ta, vb, va = tb + b["instructions"], ta + a["instructions"], vb + b["temps"], va + a["temps"]
    if len(reports) > 1:
        rows.append(("всего", f"{tb} -> {ta}", f"{vb} -> {va}", ""))
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def changes_text(reports):
    lines = []
    for name, r in reports.items():
        ch = ", ".join(f"{k} {v}" for k, v in r["changes"].items() if v) or "нет изменений"
        lines.append(f"{name}: проходов {r['rounds']}; изменений: {ch}")
    return "\n".join(lines)


def run_hw4(module, flags):
    """Всё, что касается IR. Возвращает код выхода."""
    from funny_ir import format_module, module_to_json
    from funny_irgen import generate
    from funny_opt import optimize
    from funny_cfg import build_cfg, liveness, format_cfg, cfg_to_dot
    from funny_regalloc import allocate, format_interference, interference_to_dot, interference_to_json
    from funny_irinterp import run, parse_call, format_result

    passes, regs, color_all = hw4_settings(flags)
    before = generate(module)
    after, reports = optimize(before, passes)
    graphs = {f.name: allocate(f, color_all, regs) for f in after.functions}
    title = ", ".join(passes) or "все выключены"
    status = 0

    def cfgs(ir):
        result = []
        for f in ir.functions:
            c = build_cfg(f)
            liveness(c)
            result.append(c)
        return result

    if "--ir" in flags:
        print("=== IR до оптимизаций ===")
        print(format_module(before))
        print(f"=== IR после оптимизаций ({title}) ===")
        print(format_module(after))
        print("=== Изменения ===")
        print(changes_text(reports))
        print("\n=== Метрики ===")
        print(metrics_table(reports, graphs))
    if "--ir-json" in flags:
        print(json.dumps(module_to_json(after), ensure_ascii=False, indent=2))
    if "--cfg" in flags:
        print("\n\n".join(format_cfg(c) for c in cfgs(after)))
    if "--cfg-dot" in flags:
        print("".join(cfg_to_dot(c) for c in cfgs(after)), end="")
    if "--interference" in flags:
        print("\n".join(format_interference(g) for g in graphs.values()))
    if "--interference-dot" in flags:
        print("".join(interference_to_dot(g) for g in graphs.values()), end="")

    call = flag_value(flags, "--run")
    if call:
        try:
            name, args = parse_call(call)
        except ValueError as e:
            sys.exit(f"ошибка в --run: {e}")
        if before.function(name) is None:
            sys.exit(f"ошибка в --run: нет функции {name}")
        r1, r2 = run(before, name, args), run(after, name, args)
        print(f"{call}")
        print(f"    до оптимизаций:    {format_result(r1)}")
        print(f"    после оптимизаций: {format_result(r2)}")
        print("    совпадает" if r1 == r2 else "    РАЗЛИЧАЮТСЯ!")
        status = 0 if r1 == r2 else 1

    out_dir = flag_value(flags, "--out-dir")
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

        def save(name, text):
            with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        save("ir_before.txt", format_module(before))
        save("ir_after.txt", format_module(after))
        save("ir_before.json", json.dumps(module_to_json(before), ensure_ascii=False, indent=2) + "\n")
        save("ir_after.json", json.dumps(module_to_json(after), ensure_ascii=False, indent=2) + "\n")
        save("cfg.txt", "\n\n".join(format_cfg(c) for c in cfgs(after)) + "\n")
        save("interference.txt", "\n".join(format_interference(g) for g in graphs.values()) + "\n")
        save("metrics.txt", f"оптимизации: {title}\n\n" + metrics_table(reports, graphs) + "\n\n"
             + changes_text(reports) + "\n")
        save("metrics.json", json.dumps({
            "optimizations": passes,
            "functions": {n: {**r, "colors": graphs[n].num_colors} for n, r in reports.items()},
            "interference": [interference_to_json(g) for g in graphs.values()],
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"записано в {out_dir}", file=sys.stderr)
    return status


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    path = args[0]

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    with open(path, encoding="utf-8-sig") as f:   
        text = f.read()

    status = 0
    if "--tokens" in flags:
        tokens, errors = tokenize(text)
        for t in tokens:
            print(f"{t.line:>3}:{t.col:<3} {t.kind:<13} {t.text}")
    else:
        module, errors = parse(text)
        if not errors:                             # синтаксис в порядке — печатаем дерево
            if "--parse-only" not in flags:
                errors = check(module)             # HW3: имена и типы; дерево получает типы
            if any(has_flag(flags, f) for f in HW4_SETTINGS) and \
                    not any(has_flag(flags, f) for f in HW4_FLAGS):
                flags.append("--ir")               # указали только настройки — показываем IR
            if any(has_flag(flags, f) for f in HW4_FLAGS):
                if not errors:                     # IR строим только для правильной программы
                    status = run_hw4(module, flags)
            elif "--json" in flags:
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
    sys.exit(1 if errors else status)


if __name__ == "__main__":
    main()
