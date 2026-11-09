"""
funny_irinterp.py — интерпретатор трёхадресного кода (HW4).

Нужен для проверки оптимизаций: одна и та же функция с одними входами должна дать
одинаковый результат до и после оптимизаций (или одинаково упасть).

Семантика — как в funny.ru.md и будущем JVM-коде:
    int — 32 бита со знаком, переполнение по модулю 2^32 (Integer в Java);
    деление — с отбрасыванием дробной части к нулю; деление на 0 — ошибка;
    массив — неизменяемый (кортеж Python), update создаёт новый;
    load / update с индексом вне [0, length) — ошибка;
    функция возвращает значения своих return-переменных.
Чтение непроинициализированной переменной в Funny не определено; интерпретатор даёт 0
(для int[] — пустой массив). Это совпадает с тем, что сделает JVM при инициализации нулём,
и одинаково для кода до и после оптимизаций.
"""
from funny_ir import (is_var, Label, Copy, BinOp, UnOp, Length, Load, Update, Goto, IfGoto,
                      Call, Return, ARRAY)
from funny_opt import eval_binop, wrap


class FunnyRuntimeError(Exception):
    """Ошибка времени выполнения программы Funny (деление на 0, выход за границы)."""


class StepLimit(Exception):
    """Программа выполняется слишком долго (вероятно, бесконечный цикл)."""


class Interpreter:
    def __init__(self, module, max_steps=1_000_000, max_depth=200):
        self.module = module
        self.max_steps = max_steps
        self.max_depth = max_depth
        self.steps = 0
        self._labels = {}

    def labels(self, fn):
        if fn.name not in self._labels:
            self._labels[fn.name] = {ins.name: i for i, ins in enumerate(fn.code) if isinstance(ins, Label)}
        return self._labels[fn.name]

    def call(self, name, args, depth=0):
        fn = self.module.function(name)
        if fn is None:
            raise FunnyRuntimeError(f"нет функции {name}")
        if depth > self.max_depth:
            raise FunnyRuntimeError("слишком глубокая рекурсия")
        env = {n: a for (n, _), a in zip(fn.params, args)}

        def get(x):
            if not is_var(x):
                return x
            if x not in env:                      # не определено в Funny; берём «ноль»
                return () if fn.type_of(x) == ARRAY else 0
            return env[x]

        labels = self.labels(fn)
        pc = 0
        while pc < len(fn.code):
            self.steps += 1
            if self.steps > self.max_steps:
                raise StepLimit()
            ins = fn.code[pc]
            pc += 1
            if isinstance(ins, Label):
                continue
            if isinstance(ins, Copy):
                env[ins.dst] = get(ins.src)
            elif isinstance(ins, BinOp):
                a, b = get(ins.left), get(ins.right)
                value = eval_binop(ins.op, a, b)
                if value is None:
                    raise FunnyRuntimeError("деление на ноль")
                env[ins.dst] = value
            elif isinstance(ins, UnOp):
                env[ins.dst] = wrap(-get(ins.arg))
            elif isinstance(ins, Length):
                env[ins.dst] = len(get(ins.array))
            elif isinstance(ins, Load):
                arr, i = get(ins.array), get(ins.index)
                if not 0 <= i < len(arr):
                    raise FunnyRuntimeError(f"индекс {i} вне массива длины {len(arr)}")
                env[ins.dst] = arr[i]
            elif isinstance(ins, Update):
                arr, i, v = get(ins.array), get(ins.index), get(ins.value)
                if not 0 <= i < len(arr):
                    raise FunnyRuntimeError(f"индекс {i} вне массива длины {len(arr)}")
                env[ins.dst] = arr[:i] + (v,) + arr[i + 1:]
            elif isinstance(ins, Goto):
                pc = labels[ins.label]
            elif isinstance(ins, IfGoto):
                if get(ins.cond):
                    pc = labels[ins.label]
            elif isinstance(ins, Call):
                results = self.call(ins.func, [get(a) for a in ins.args], depth + 1)
                for d, r in zip(ins.dsts, results):
                    env[d] = r
            elif isinstance(ins, Return):
                return tuple(get(v) for v in ins.values)
        raise FunnyRuntimeError(f"функция {name} закончилась без return")


def run(module, name, args, max_steps=1_000_000):
    """Выполнить функцию. Результат: ("ok", значения) или ("error", текст) или ("timeout", None)."""
    try:
        return "ok", Interpreter(module, max_steps).call(name, list(args))
    except FunnyRuntimeError as e:
        return "error", str(e)
    except StepLimit:
        return "timeout", None


# ---------- значения в тексте: 5, -3, [1, 2, 3] ----------

def parse_value(text):
    text = text.strip()
    if text.startswith("["):
        inner = text[1:-1].strip()
        return tuple(wrap(int(x)) for x in inner.split(",")) if inner else ()
    return wrap(int(text))


def split_args(text):
    """'1, [2, 3], -4' -> ['1', '[2, 3]', '-4'] (запятые внутри [] не делят)."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts]


def parse_call(text):
    """'f(1, [2, 3])' -> ('f', [1, (2, 3)])"""
    text = text.strip()
    name, rest = text.split("(", 1)
    if not rest.endswith(")"):
        raise ValueError(f"ожидался вызов вида f(1, [2, 3]), а не {text!r}")
    return name.strip(), [parse_value(a) for a in split_args(rest[:-1])]


def format_value(v):
    if isinstance(v, tuple):
        return "[" + ", ".join(str(x) for x in v) + "]"
    return str(v)


def format_result(result):
    status, value = result
    if status == "ok":
        return ", ".join(format_value(v) for v in value)
    if status == "error":
        return f"ошибка: {value}"
    return "превышен лимит шагов"
