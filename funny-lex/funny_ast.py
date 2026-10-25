"""
funny_ast.py — узлы абстрактного синтаксического дерева (AST) языка Funny.

Каждый узел — это dataclass. Поля узла — его дети (другие узлы или списки узлов)
и простые значения (имя, оператор, число). У каждого узла есть pos = (строка, столбец)
— позиция в исходном тексте, по ней следующие этапы (HW3, проект) пишут ошибки.

Две функции печати:
    to_json(node) — словари/списки для json.dumps (формат для следующих этапов);
    dump(node)    — человеко-читаемое дерево с отступами (для глаз и snapshot-тестов).

HW3 (аннотированный AST): у каждого выражения есть поле type — его тип после
семантического анализа ("int", "int[]", "bool", "(int, int)"); до анализа там None.
У Function появляется поле locals — локальные переменные с выведенными типами.

Полное описание формата — в AST.md.
"""
from dataclasses import dataclass, fields


class Node:
    """Общий предок всех узлов (нужен, чтобы отличать узлы от обычных значений)."""


class Expr(Node):
    """Общий предок выражений: у них есть поле type (HW3), его dump печатает как  : тип"""


# 1. ВЕРХНИЙ УРОВЕНЬ

@dataclass
class Module(Node):
    items: list              # Function и Formula в порядке появления
    pos: tuple = (1, 1)


@dataclass
class VarDef(Node):
    """Объявление переменной: параметр, возвращаемое значение, локальная (uses), переменная квантора."""
    name: str
    type: str                # "int", "int[]" или None (локальная без типа в uses)
    pos: tuple = (0, 0)


@dataclass
class Function(Node):
    name: str
    params: list             # [VarDef]
    requires: Node           # предикат или None (по умолчанию true)
    returns: list            # [VarDef], хотя бы одно
    ensures: Node            # предикат или None (по умолчанию false — см. funny.ru.md)
    uses: list               # [VarDef] локальные переменные из uses (часто пусто)
    body: Node               # оператор (обычно Block)
    pos: tuple = (0, 0)
    locals: list = None      # HW3: [VarDef] локальные переменные с выведенными типами


@dataclass
class Formula(Node):
    name: str
    params: list             # [VarDef]
    body: Node               # предикат
    pos: tuple = (0, 0)


# 2. ОПЕРАТОРЫ

@dataclass
class Assign(Node):
    """x = e;   x, y = f(...);   и обессахаренное a[i] = v  (тогда value — ArrayUpdate)."""
    targets: list            # имена переменных слева: ["x"] или ["x", "y"]
    value: Node
    pos: tuple = (0, 0)


@dataclass
class If(Node):
    cond: Node
    then_branch: Node
    else_branch: Node        # None, если else нет
    pos: tuple = (0, 0)


@dataclass
class While(Node):
    cond: Node
    invariant: Node          # None, если не указан (по умолчанию true)
    body: Node
    pos: tuple = (0, 0)


@dataclass
class Block(Node):
    stmts: list
    pos: tuple = (0, 0)


@dataclass
class Assert(Node):
    pred: Node
    pos: tuple = (0, 0)


@dataclass
class Assume(Node):
    pred: Node
    pos: tuple = (0, 0)


# 3. ВЫРАЖЕНИЯ, УСЛОВИЯ И ПРЕДИКАТЫ
# В AST это одни и те же узлы: "a + 1", "a < b", "x > 0 and y > 0" — всё Binary.
# Что где допустимо (int или логическое) — проверяет семантика (HW3), не парсер.

@dataclass
class Num(Expr):
    value: int
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


@dataclass
class Bool(Expr):
    value: bool
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


@dataclass
class Var(Expr):
    name: str
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


@dataclass
class Unary(Expr):
    op: str                  # "-" или "not"
    operand: Node
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


@dataclass
class Binary(Expr):
    op: str                  # + - * /   == != < <= > >=   and or ->
    left: Node
    right: Node
    pos: tuple = (0, 0)      # позиция оператора
    type: object = None      # HW3: тип выражения


@dataclass
class Call(Expr):
    """Вызов функции f(...), length(a) или ссылка на формулу is_sorted(a, 0, n)."""
    name: str
    args: list
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


@dataclass
class Index(Expr):
    """Чтение элемента массива: a[i]."""
    array: str
    index: Node
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


@dataclass
class ArrayUpdate(Expr):
    """Функциональное обновление: НОВЫЙ массив, равный array, но с value на месте index.
    Получается только из сахара  a[i] = v;  ->  a = ArrayUpdate(a, i, v)  (в funny.ru.md: a = set(a, i, v))."""
    array: str
    index: Node
    value: Node
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


@dataclass
class Quantifier(Expr):
    kind: str                # "forall" или "exists"
    var: Node                # VarDef
    body: Node               # предикат
    pos: tuple = (0, 0)
    type: object = None      # HW3: тип выражения


# 4. ПЕЧАТЬ

def to_json(value):
    """Узел -> словарь {"node": "Имя", поля..., "line": .., "col": ..}. Списки — поэлементно."""
    if isinstance(value, Node):
        result = {"node": type(value).__name__}
        for f in fields(value):
            v = getattr(value, f.name)
            if f.name == "pos":
                result["line"], result["col"] = v
            else:
                result[f.name] = to_json(v)
        return result
    if isinstance(value, list):
        return [to_json(v) for v in value]
    return value                                   # str, int, bool, None — как есть


def dump(node):
    """Узел -> текст дерева. Пример:
        Assign s  @3:5
          value: Binary +  @3:11
            left: Var s  @3:9
            right: Num 1  @3:13
    """
    lines = []
    _dump(node, 0, "", lines)
    return "\n".join(lines)


def _is_child(v):
    """Поле — это ребёнок (узел или непустой список узлов), а не простое значение?"""
    return isinstance(v, Node) or (isinstance(v, list) and len(v) > 0 and isinstance(v[0], Node))


def _show(v):
    """Простое значение для печати в строке узла."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def _dump(node, depth, label, lines):
    pad = "  " * depth
    simple = []                                    # простые поля — в строку узла
    children = []                                  # дети — ниже, с отступом
    for f in fields(node):
        v = getattr(node, f.name)
        if f.name == "pos" or v is None or v == []:
            continue                               # пустые поля не печатаем
        if f.name == "type" and isinstance(node, Expr):
            continue                               # тип выражения печатается отдельно, через ':' 
        if _is_child(v):
            children.append((f.name, v))
        else:
            simple.append(_show(v))

    head = " ".join([type(node).__name__] + simple)
    if isinstance(node, Expr) and node.type is not None:
        head += f" : {node.type}"                  # HW3: тип выражения
    lines.append(f"{pad}{label}{head}  @{node.pos[0]}:{node.pos[1]}")

    for name, v in children:
        if isinstance(v, list):                    # список: подпись, элементы ниже
            lines.append(f"{pad}  {name}:")
            for item in v:
                _dump(item, depth + 2, "", lines)
        else:                                      # один ребёнок: подпись в той же строке
            _dump(v, depth + 1, name + ": ", lines)


def walk(node):
    """Все узлы дерева по очереди (сам node, потом дети в глубину). Пригодится в HW3/HW4."""
    yield node
    for f in fields(node):
        v = getattr(node, f.name)
        children = v if isinstance(v, list) else [v]
        for child in children:
            if isinstance(child, Node):
                yield from walk(child)
