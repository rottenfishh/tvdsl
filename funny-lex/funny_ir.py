"""
funny_ir.py — промежуточное представление (IR) Funny: трёхадресный код (HW4).

Набор инструкций взят из лекции 6 («Пример для Funny: набор инструкций»):

    L:                              Label        метка
    x := c   /   x := y             Copy         копирование константы или переменной
    x := y op z                     BinOp        op: + - * /   == != < <= > >=
    x := op y                       UnOp         op: -   (унарный минус)
    x := length a                   Length       встроенная length(a)
    x := load a[i]                  Load         чтение элемента массива
    x := update(a, i, y)            Update       НОВЫЙ массив: a с y на месте i (a не меняется)
    if x goto L                     IfGoto       перейти на L, если x == true
    goto L                          Goto
    x1, ..., xm := call f(a1, ..., an)   Call    вызов функции модуля
    return x1, ..., xm              Return       значения в порядке returns

Операнд — это либо имя переменной (str), либо константа: int или bool (true/false).
Константа может стоять везде, где читается значение: x := 5, t := a + 1, if true goto L, return 0.

У каждой переменной есть тип: "int", "int[]" или "bool" (bool бывает только у временных —
результатов сравнений; в Funny нет bool-переменных). Типы нужны кодогенерации:
по ним выбираются JVM-инструкции (iload/aload, int/ImmutableIntArray).

Полное описание формата (текст и JSON) — в IR.md.
"""
from dataclasses import dataclass, field

INT, ARRAY, BOOL = "int", "int[]", "bool"


# ---------- операнды ----------

def is_var(x):
    """Операнд — переменная (а не константа)?"""
    return isinstance(x, str)


def show(x):
    """Операнд -> текст. bool проверяем раньше int: в Python True — это тоже int."""
    if isinstance(x, bool):
        return "true" if x else "false"
    return str(x)


# ---------- инструкции ----------
# У каждой инструкции два метода, на которых держатся все анализы и оптимизации:
#   defs() — какие переменные она записывает;
#   uses() — какие переменные она читает (константы не в счёт).
# И метод replace(mapping) — заменить читаемые переменные (для распространения констант/копий).


def _rep(x, mapping):
    return mapping.get(x, x) if is_var(x) else x


@dataclass
class Instr:
    def defs(self):
        return []

    def uses(self):
        return []

    def replace(self, mapping):
        """Заменить ЧИТАЕМЫЕ операнды по словарю имя -> операнд. Записываемые не трогаем."""


@dataclass
class Label(Instr):
    name: str

    def __str__(self):
        return f"{self.name}:"


@dataclass
class Copy(Instr):
    dst: str
    src: object

    def defs(self):
        return [self.dst]

    def uses(self):
        return [self.src] if is_var(self.src) else []

    def replace(self, m):
        self.src = _rep(self.src, m)

    def __str__(self):
        return f"{self.dst} := {show(self.src)}"


@dataclass
class BinOp(Instr):
    dst: str
    op: str
    left: object
    right: object

    def defs(self):
        return [self.dst]

    def uses(self):
        return [x for x in (self.left, self.right) if is_var(x)]

    def replace(self, m):
        self.left, self.right = _rep(self.left, m), _rep(self.right, m)

    def __str__(self):
        return f"{self.dst} := {show(self.left)} {self.op} {show(self.right)}"


@dataclass
class UnOp(Instr):
    dst: str
    op: str                  # только "-"
    arg: object

    def defs(self):
        return [self.dst]

    def uses(self):
        return [self.arg] if is_var(self.arg) else []

    def replace(self, m):
        self.arg = _rep(self.arg, m)

    def __str__(self):
        return f"{self.dst} := {self.op}{show(self.arg)}"


@dataclass
class Length(Instr):
    dst: str
    array: str

    def defs(self):
        return [self.dst]

    def uses(self):
        return [self.array]

    def replace(self, m):
        self.array = _rep(self.array, m)

    def __str__(self):
        return f"{self.dst} := length {self.array}"


@dataclass
class Load(Instr):
    dst: str
    array: str
    index: object

    def defs(self):
        return [self.dst]

    def uses(self):
        return [self.array] + ([self.index] if is_var(self.index) else [])

    def replace(self, m):
        self.array, self.index = _rep(self.array, m), _rep(self.index, m)

    def __str__(self):
        return f"{self.dst} := load {self.array}[{show(self.index)}]"


@dataclass
class Update(Instr):
    dst: str
    array: str
    index: object
    value: object

    def defs(self):
        return [self.dst]

    def uses(self):
        return [x for x in (self.array, self.index, self.value) if is_var(x)]

    def replace(self, m):
        self.array, self.index, self.value = (_rep(self.array, m), _rep(self.index, m),
                                              _rep(self.value, m))

    def __str__(self):
        return f"{self.dst} := update({self.array}, {show(self.index)}, {show(self.value)})"


@dataclass
class Goto(Instr):
    label: str

    def __str__(self):
        return f"goto {self.label}"


@dataclass
class IfGoto(Instr):
    cond: object
    label: str

    def uses(self):
        return [self.cond] if is_var(self.cond) else []

    def replace(self, m):
        self.cond = _rep(self.cond, m)

    def __str__(self):
        return f"if {show(self.cond)} goto {self.label}"


@dataclass
class Call(Instr):
    dsts: list
    func: str
    args: list

    def defs(self):
        return list(self.dsts)

    def uses(self):
        return [a for a in self.args if is_var(a)]

    def replace(self, m):
        self.args = [_rep(a, m) for a in self.args]

    def __str__(self):
        return f"{', '.join(self.dsts)} := call {self.func}({', '.join(show(a) for a in self.args)})"


@dataclass
class Return(Instr):
    values: list

    def uses(self):
        return [v for v in self.values if is_var(v)]

    def replace(self, m):
        self.values = [_rep(v, m) for v in self.values]

    def __str__(self):
        return "return " + ", ".join(show(v) for v in self.values)


JUMPS = (Goto, IfGoto, Return)        # после них начинается новый базовый блок


# ---------- функция и модуль ----------

@dataclass
class IRFunction:
    name: str
    params: list                 # [(имя, тип)] в порядке объявления
    returns: list                # [(имя, тип)]
    locals: list                 # [(имя, тип)] локальные переменные Funny
    temps: dict = field(default_factory=dict)    # имя временной -> тип
    code: list = field(default_factory=list)     # [Instr]

    def type_of(self, name):
        for n, t in self.params + self.returns + self.locals:
            if n == name:
                return t
        return self.temps.get(name)

    def is_temp(self, name):
        return name in self.temps


@dataclass
class IRModule:
    functions: list              # [IRFunction]

    def function(self, name):
        for f in self.functions:
            if f.name == name:
                return f
        return None


# ---------- печать ----------

def format_function(fn):
    """Текстовый вид функции: заголовок, переменные, код (метки без отступа)."""
    def decl(vs):
        return ", ".join(f"{n}: {t}" for n, t in vs)
    lines = [f"function {fn.name}({decl(fn.params)}) returns {decl(fn.returns)}"]
    if fn.locals:
        lines.append(f"    locals {decl(fn.locals)}")
    if fn.temps:
        lines.append(f"    temps  {decl(fn.temps.items())}")
    for ins in fn.code:
        lines.append(str(ins) if isinstance(ins, Label) else "    " + str(ins))
    lines.append("end")
    return "\n".join(lines)


def format_module(module):
    return "\n\n".join(format_function(f) for f in module.functions) + "\n"


# ---------- JSON ----------
# Операнды в JSON: имя переменной — строка, константа — число или true/false.

def instr_to_json(ins):
    kind = type(ins).__name__
    if isinstance(ins, Label):
        return {"op": "label", "name": ins.name}
    if isinstance(ins, Copy):
        return {"op": "copy", "dst": ins.dst, "src": ins.src}
    if isinstance(ins, BinOp):
        return {"op": "binop", "dst": ins.dst, "operator": ins.op, "left": ins.left, "right": ins.right}
    if isinstance(ins, UnOp):
        return {"op": "unop", "dst": ins.dst, "operator": ins.op, "arg": ins.arg}
    if isinstance(ins, Length):
        return {"op": "length", "dst": ins.dst, "array": ins.array}
    if isinstance(ins, Load):
        return {"op": "load", "dst": ins.dst, "array": ins.array, "index": ins.index}
    if isinstance(ins, Update):
        return {"op": "update", "dst": ins.dst, "array": ins.array, "index": ins.index, "value": ins.value}
    if isinstance(ins, Goto):
        return {"op": "goto", "label": ins.label}
    if isinstance(ins, IfGoto):
        return {"op": "if", "cond": ins.cond, "label": ins.label}
    if isinstance(ins, Call):
        return {"op": "call", "dsts": ins.dsts, "func": ins.func, "args": ins.args}
    if isinstance(ins, Return):
        return {"op": "return", "values": ins.values}
    raise ValueError(kind)


def function_to_json(fn):
    def vs(pairs):
        return [{"name": n, "type": t} for n, t in pairs]
    return {
        "name": fn.name,
        "params": vs(fn.params),
        "returns": vs(fn.returns),
        "locals": vs(fn.locals),
        "temps": vs(fn.temps.items()),
        "code": [instr_to_json(i) for i in fn.code],
    }


def module_to_json(module):
    return {"functions": [function_to_json(f) for f in module.functions]}


# ---------- метрики ----------

def metrics(fn):
    """Сколько инструкций (без меток) и временных реально используется в коде."""
    used_temps = set()
    for ins in fn.code:
        for v in ins.defs() + ins.uses():
            if fn.is_temp(v):
                used_temps.add(v)
    return {
        "instructions": sum(1 for i in fn.code if not isinstance(i, Label)),
        "temps": len(used_temps),
    }
