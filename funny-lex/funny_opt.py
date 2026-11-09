"""
funny_opt.py — оптимизации трёхадресного кода (HW4).

Проходы (каждый можно выключить флагом, см. funny.py и README):

    constprop    распространение и свёртка констант: x := 3; y := x + 4  ->  y := 7;
                 if true goto L -> goto L;  if false goto L -> (удаляется)
    algebra      алгебраические упрощения: x + 0, x - 0, x * 1, x / 1 -> x;  x * 0 -> 0;
                 x - x -> 0;  x * 2 -> x + x;  x == x -> true;  x < x -> false
    copies       распространение копий (x := y; z := x + 1 -> z := y + 1) и «склейка»
                 t := a + b; x := t  ->  x := a + b  (t — временная, используется один раз)
    cse          общие подвыражения в блоке: t1 := a + b; t2 := a + b -> t2 := t1
    dce          удаление бесполезного кода: x := e, если x мертва после команды
                 и e не может упасть (деление на переменную, load, update, call не удаляем)
    unreachable  удаление недостижимых блоков, goto на следующую строку, неиспользуемых меток

constprop, algebra, copies, cse — ЛОКАЛЬНЫЕ: работают внутри одного базового блока
(на границе блока всё, что знали о значениях, забываем — туда можно прийти другим путём).
dce тоже локальный (идёт по блоку снизу вверх), но знает, какие переменные живы на выходе
блока, из глобального анализа живости (funny_cfg.liveness).

Проходы повторяются по кругу, пока код меняется: свёртка констант открывает работу
для DCE, удаление меток склеивает блоки — и локальные проходы видят больше.

Семантика чисел — как в JVM: 32-битные int с переполнением, деление с отбрасыванием
дробной части к нулю, деление на 0 — исключение (поэтому такое деление не сворачиваем).
"""
import copy
from collections import Counter

from funny_ir import (is_var, show, metrics, Label, Copy, BinOp, UnOp, Length, Load, Update,
                      Goto, IfGoto, Call)
from funny_cfg import build_cfg, liveness, reachable, CFG

PASSES = ["constprop", "algebra", "copies", "cse", "dce", "unreachable"]
COMMUTATIVE = {"+", "*", "==", "!="}


# ---------- арифметика как в JVM ----------

def wrap(n):
    """Привести к 32-битному int со знаком (переполнение по модулю 2^32)."""
    n &= 0xFFFFFFFF
    return n - (1 << 32) if n >= (1 << 31) else n


def java_div(a, b):
    """Целочисленное деление Java: дробная часть отбрасывается (к нулю). Делитель не 0."""
    q = abs(a) // abs(b)
    return wrap(q if (a >= 0) == (b >= 0) else -q)


def eval_binop(op, a, b):
    """Значение a op b для констант или None, если вычислять нельзя (деление на 0)."""
    if op == "+":
        return wrap(a + b)
    if op == "-":
        return wrap(a - b)
    if op == "*":
        return wrap(a * b)
    if op == "/":
        return None if b == 0 else java_div(a, b)
    return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def is_const(x, value=None):
    """Операнд — числовая константа (а если указан value — именно это число)?"""
    if is_var(x) or isinstance(x, bool):
        return False
    return value is None or x == value


# ---------- проходы внутри блока ----------
# Каждый проход получает список инструкций блока и счётчик изменений stats[имя].

def constprop_block(instrs, stats):
    env = {}                                   # переменная -> известная константа
    out = []
    for ins in instrs:
        if env:
            before = str(ins)
            ins.replace(env)
            if str(ins) != before:
                stats["constprop"] += 1
        folded = fold(ins)
        if folded is not ins:
            stats["constprop"] += 1
            if folded is None:                 # if false goto L — переход никогда не срабатывает
                continue
            ins = folded
        for d in ins.defs():
            env.pop(d, None)
        if isinstance(ins, Copy) and not is_var(ins.src):
            env[ins.dst] = ins.src
        out.append(ins)
    return out


def fold(ins):
    """Свёртка: операция над константами -> копия константы. None — инструкцию удалить."""
    if isinstance(ins, BinOp) and not is_var(ins.left) and not is_var(ins.right):
        value = eval_binop(ins.op, ins.left, ins.right)
        return ins if value is None else Copy(ins.dst, value)
    if isinstance(ins, UnOp) and not is_var(ins.arg):
        return Copy(ins.dst, wrap(-ins.arg))
    if isinstance(ins, IfGoto) and not is_var(ins.cond):
        return Goto(ins.label) if ins.cond else None
    return ins


def algebra_block(instrs, stats):
    out = []
    for ins in instrs:
        new = simplify(ins)
        if new is not ins:
            stats["algebra"] += 1
        out.append(new)
    return out


def simplify(ins):
    """Одно алгебраическое упрощение BinOp. Небезопасные правила не применяем:
    0 / x и x / x могут упасть при x == 0, а после «упрощения» не упадут."""
    if not isinstance(ins, BinOp):
        return ins
    op, a, b, d = ins.op, ins.left, ins.right, ins.dst
    same = is_var(a) and a == b
    if op == "+":
        if is_const(b, 0):
            return Copy(d, a)
        if is_const(a, 0):
            return Copy(d, b)
    elif op == "-":
        if is_const(b, 0):
            return Copy(d, a)
        if same:
            return Copy(d, 0)
        if is_const(a, 0):
            return UnOp(d, "-", b)
    elif op == "*":
        if is_const(b, 1):
            return Copy(d, a)
        if is_const(a, 1):
            return Copy(d, b)
        if is_const(a, 0) or is_const(b, 0):
            return Copy(d, 0)
        if is_const(b, -1):
            return UnOp(d, "-", a)
        if is_const(a, -1):
            return UnOp(d, "-", b)
        if is_const(b, 2):                     # снижение стоимости: умножение -> сложение
            return BinOp(d, "+", a, a)
        if is_const(a, 2):
            return BinOp(d, "+", b, b)
    elif op == "/":
        if is_const(b, 1):
            return Copy(d, a)
        if is_const(b, -1):
            return UnOp(d, "-", a)
    elif same and op in ("==", "<=", ">="):
        return Copy(d, True)
    elif same and op in ("!=", "<", ">"):
        return Copy(d, False)
    return ins


def copies_block(instrs, stats):
    """Распространение копий: после x := y читаем y вместо x, пока ни x, ни y не переписаны."""
    env = {}                                   # x -> y
    out = []
    for ins in instrs:
        if env:
            before = str(ins)
            ins.replace(env)
            if str(ins) != before:
                stats["copies"] += 1
        if isinstance(ins, Copy) and ins.src == ins.dst:
            stats["copies"] += 1               # x := x — ничего не делает
            continue
        for d in ins.defs():
            env.pop(d, None)
            for k in [k for k, v in env.items() if v == d]:
                del env[k]
        if isinstance(ins, Copy) and is_var(ins.src):
            env[ins.dst] = ins.src
        out.append(ins)
    return out


def _operand_key(x):
    return ("v", x) if is_var(x) else ("c", show(x))


def expr_key(ins):
    """Ключ вычисляемого выражения для CSE (у равных выражений — равные ключи) или None."""
    if isinstance(ins, BinOp):
        a, b = _operand_key(ins.left), _operand_key(ins.right)
        if ins.op in COMMUTATIVE and b < a:
            a, b = b, a
        return (ins.op, a, b)
    if isinstance(ins, UnOp):
        return (ins.op, _operand_key(ins.arg))
    if isinstance(ins, Length):
        return ("length", _operand_key(ins.array))
    if isinstance(ins, Load):
        return ("load", _operand_key(ins.array), _operand_key(ins.index))
    if isinstance(ins, Update):
        return ("update", _operand_key(ins.array), _operand_key(ins.index), _operand_key(ins.value))
    return None                                # call не трогаем — консервативно


def _key_vars(key):
    return {part[1] for part in key[1:] if part[0] == "v"}


def cse_block(instrs, stats):
    """Общие подвыражения: если выражение уже посчитано в переменной v и его операнды
    с тех пор не менялись, вместо повторного вычисления пишем x := v.
    Массивы в Funny неизменяемые, поэтому load a[i] тоже можно переиспользовать."""
    available = {}                             # ключ выражения -> переменная, где лежит значение
    out = []
    for ins in instrs:
        key = expr_key(ins)
        if key is not None and key in available:
            ins = Copy(ins.dst, available[key])
            stats["cse"] += 1
            key = None
        defs = set(ins.defs())
        for k, v in list(available.items()):  # переписали операнд или хранилище — забываем
            if v in defs or _key_vars(k) & defs:
                del available[k]
        if key is not None and ins.dst not in _key_vars(key):
            available[key] = ins.dst
        out.append(ins)
    return out


# ---------- проходы по всей функции ----------

def _set_def(ins, old, new):
    if isinstance(ins, Call):
        ins.dsts = [new if d == old else d for d in ins.dsts]
    else:
        ins.dst = new


def coalesce(fn, cfg, stats):
    """t := <выражение>; ... ; x := t   ->   x := <выражение>
    Можно, если t — временная, записывается и читается ровно по разу, оба места в одном блоке,
    а между ними x не читается и не пишется."""
    use_count = Counter(v for ins in fn.code for v in ins.uses())
    def_count = Counter(v for ins in fn.code for v in ins.defs())
    for b in cfg.blocks:
        i = 0
        while i < len(b.instrs):
            ins = b.instrs[i]
            t = ins.src if isinstance(ins, Copy) else None
            if is_var(t) and fn.is_temp(t) and use_count[t] == 1 and def_count[t] == 1:
                j = next((k for k in range(i - 1, -1, -1) if t in b.instrs[k].defs()), None)
                between = b.instrs[j + 1:i] if j is not None else []
                x = ins.dst
                if j is not None and x not in b.instrs[j].defs() and \
                        all(x not in m.uses() and x not in m.defs() for m in between):
                    _set_def(b.instrs[j], t, x)
                    del b.instrs[i]
                    stats["copies"] += 1
                    continue
            i += 1


def removable(ins):
    """Можно ли удалить инструкцию, если её результат не нужен:
    нет побочных эффектов и она не может упасть (лекция 6, «Удаление бесполезного кода»)."""
    if isinstance(ins, (Copy, UnOp, Length)):
        return True
    if isinstance(ins, BinOp):
        return ins.op != "/" or (is_const(ins.right) and ins.right != 0)
    return False                               # load/update — выход за границы, call — что угодно


def dce(cfg, stats):
    liveness(cfg)
    for b in cfg.blocks:
        live = set(b.live_out)
        kept = []
        for ins in reversed(b.instrs):
            defs = set(ins.defs())
            if defs and removable(ins) and not (defs & live):
                stats["dce"] += 1
                continue
            live = (live - defs) | set(ins.uses())
            kept.append(ins)
        b.instrs = kept[::-1]


def remove_unreachable(fn, stats):
    """Недостижимые блоки, goto на следующую строку, метки без переходов."""
    cfg = build_cfg(fn)
    alive = reachable(cfg)
    code = []
    for b in cfg.blocks:
        if b.name in alive:
            code += b.instrs
        else:
            stats["unreachable"] += sum(1 for i in b.instrs if not isinstance(i, Label))
    changed = True
    while changed:
        changed = False
        for i, ins in enumerate(code):
            nxt = code[i + 1] if i + 1 < len(code) else None
            if isinstance(ins, (Goto, IfGoto)) and isinstance(nxt, Label) and nxt.name == ins.label:
                del code[i]                    # переход на следующую строку — и так туда попадём
                stats["unreachable"] += 1
                changed = True
                break
        targets = {i.label for i in code if isinstance(i, (Goto, IfGoto))}
        before = len(code)
        code = [i for i in code if not isinstance(i, Label) or i.name in targets]
        changed = changed or len(code) != before
    fn.code = code


# ---------- менеджер проходов ----------

LOCAL = [("constprop", constprop_block), ("algebra", algebra_block),
         ("copies", copies_block), ("cse", cse_block)]


def optimize_function(fn, enabled, max_rounds=50):
    """Оптимизировать копию функции. Возвращает (новая функция, отчёт)."""
    fn = copy.deepcopy(fn)
    stats = Counter({p: 0 for p in PASSES})
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        before = [str(i) for i in fn.code]
        cfg = build_cfg(fn)
        for name, block_pass in LOCAL:
            if name == "copies" and name in enabled:
                # склейку делаем ДО распространения копий: иначе из  t := a + b; r := t; return r
                # получится  t := a + b; return t  (r заменили на t), а хотим  r := a + b; return r
                fn.code = cfg.code()
                coalesce(fn, cfg, stats)
            if name in enabled:
                for b in cfg.blocks:
                    b.instrs = block_pass(b.instrs, stats)
        if "dce" in enabled:
            dce(cfg, stats)
        fn.code = cfg.code()
        if "unreachable" in enabled:
            remove_unreachable(fn, stats)
        if [str(i) for i in fn.code] == before:
            break
    used = {v for ins in fn.code for v in ins.defs() + ins.uses()}
    fn.temps = {t: ty for t, ty in fn.temps.items() if t in used}
    return fn, {"rounds": rounds, "changes": dict(stats)}


def optimize(module, enabled=None):
    """Оптимизировать модуль. enabled — множество имён проходов (по умолчанию все).
    Исходный модуль не меняется. Возвращает (новый модуль, {функция: отчёт})."""
    enabled = set(PASSES if enabled is None else enabled)
    result = copy.deepcopy(module)
    reports = {}
    for i, fn in enumerate(module.functions):
        new_fn, report = optimize_function(fn, enabled)
        report["before"] = metrics(fn)
        report["after"] = metrics(new_fn)
        result.functions[i] = new_fn
        reports[fn.name] = report
    return result, reports


def parse_pass_list(text):
    """'constprop,dce' -> {'constprop', 'dce'}; неизвестное имя — ValueError."""
    names = {p.strip() for p in text.split(",") if p.strip()}
    unknown = names - set(PASSES)
    if unknown:
        raise ValueError(f"неизвестные оптимизации: {', '.join(sorted(unknown))}; есть: {', '.join(PASSES)}")
    return names
