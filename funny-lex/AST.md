# Формат AST Funny (API для следующих HW и проекта)

## Как получить AST из Python

```python
from funny_parser import parse
from funny_ast import dump, to_json, Function, Assign, ArrayUpdate

module, errors = parse(open("prog.funny", encoding="utf-8").read())
if errors:                      # список Diagnostic: .line, .col, .message; str(e) == "3:5: текст"
    for e in errors:
        print(e)
else:
    for item in module.items:   # Function и Formula в порядке появления
        if isinstance(item, Function):
            print(item.name, [p.name for p in item.params])
```

- `parse(text)` никогда не бросает исключений на неправильной программе: ошибки возвращаются списком.
  Если `errors` пуст, AST полностью соответствует программе.
  Если не пуст, AST частичный: в нём только то, что удалось разобрать. Дальше его использовать не стоит.
- Узлы — dataclass'ы из `funny_ast.py`. У каждого есть `pos = (строка, столбец)`, счёт с 1, столбцы в символах.

## Узлы

### Верхний уровень

| Узел | Поля | pos |
|---|---|---|
| `Module` | `items: [Function \| Formula]` | (1, 1) |
| `Function` | `name: str`, `params: [VarDef]`, `requires: expr \| None`, `returns: [VarDef]` (≥ 1), `ensures: expr \| None`, `uses: [VarDef]`, `body: stmt` | начало определения |
| `Formula` | `name: str`, `params: [VarDef]`, `body: expr` | имя |
| `VarDef` | `name: str`, `type: "int" \| "int[]" \| None` (`None` только в `uses`) | имя |

Значения по умолчанию (по funny.ru.md) применяет потребитель AST: `requires is None` → `true`,
`ensures is None` → `false`, `invariant is None` → `true`.

### Операторы

| Узел | Поля | pos |
|---|---|---|
| `Assign` | `targets: [str]` (одно имя или несколько для `x, y = f(...)`), `value: expr` | первое имя слева |
| `If` | `cond: expr`, `then_branch: stmt`, `else_branch: stmt \| None` | `if` |
| `While` | `cond: expr`, `invariant: expr \| None`, `body: stmt` | `while` |
| `Block` | `stmts: [stmt]` | `{` |
| `Assert` | `pred: expr` | `assert` |
| `Assume` | `pred: expr` | `assume` |

### Выражения (арифметика, условия и предикаты — одни и те же узлы)

| Узел | Поля | pos |
|---|---|---|
| `Num` | `value: int` | число |
| `Bool` | `value: bool` | `true`/`false` |
| `Var` | `name: str` | имя |
| `Unary` | `op: "-" \| "not"`, `operand: expr` | оператор |
| `Binary` | `op: + - * / == != < <= > >= and or ->`, `left`, `right` | оператор |
| `Call` | `name: str`, `args: [expr]` — вызов функции, `length(a)` или ссылка на формулу | имя |
| `Index` | `array: str`, `index: expr` — чтение `a[i]` | имя массива |
| `ArrayUpdate` | `array: str`, `index: expr`, `value: expr` — новый массив = `array` с `value` на месте `index` | имя массива |
| `Quantifier` | `kind: "forall" \| "exists"`, `var: VarDef`, `body: expr` | `forall`/`exists` |

Скобки в AST не хранятся: порядок вычисления задаёт форма дерева.
Вызов функции и ссылку на формулу парсер не различает (выглядят одинаково). Различает таблица символов в HW3.

## Обессахаривание `a[i] = v`

Парсер сразу переписывает обновление элемента в функциональное копирование
(в funny.ru.md записано как `a = set(a, i, v)`):

```
b[0] = 42;      →   Assign(targets=["b"], value=ArrayUpdate(array="b", index=Num(0), value=Num(42)))
```

После парсера отдельного узла для `a[i] = v` уже нет: это обычное присваивание переменной `b`.
Поэтому проверка «нельзя писать в параметр» (HW3) одинаково ловит и `a = ...`, и `a[0] = ...`.

## Текстовый формат (`python funny.py file.funny`, snapshot-тесты `tests/good/*.ast`)

Одна строка — один узел: имя узла, простые поля, `@строка:столбец`.
Дети идут ниже с отступом. Один ребёнок пишется как `поле: Узел`, у списка сначала идёт строка `поле:`, а элементы ниже.
Пустые поля (`None`, `[]`) не печатаются.

```
Assign b  @5:5
  value: ArrayUpdate b  @5:5
    index: Num 0  @5:7
    value: Num 42  @5:12
```

## JSON (`python funny.py file.funny --json`)

Каждый узел — объект с ключом `"node"` (имя класса), всеми полями и `"line"`/`"col"` вместо `pos`.
`None` → `null`, списки → массивы.

```json
{
  "node": "Assign",
  "targets": ["b"],
  "value": {
    "node": "ArrayUpdate",
    "array": "b",
    "index": {"node": "Num", "value": 0, "line": 5, "col": 7},
    "value": {"node": "Num", "value": 42, "line": 5, "col": 12},
    "line": 5, "col": 5
  },
  "line": 5, "col": 5
}
```

## HW3: аннотированный AST

После семантического анализа то же дерево дополнено двумя видами аннотаций.
Новых классов узлов нет: дерево из HW2 просто получает заполненные поля.

```python
from funny_semantic import analyze          # или: module, errors = parse(text); errors = check(module)

module, errors = analyze(text)               # синтаксис + семантика; ошибки — список Diagnostic
```

| Где | Поле | Значение |
|---|---|---|
| каждое выражение (`Num`, `Bool`, `Var`, `Unary`, `Binary`, `Call`, `Index`, `ArrayUpdate`, `Quantifier`) | `type: str` | `"int"`, `"int[]"`, `"bool"`, у вызова функции с несколькими результатами — `"(int, int)"`; `"error"` — в выражении нашли ошибку; до анализа — `None` |
| `Function` | `locals: [VarDef]` | все локальные переменные (из `uses` и из первых присваиваний) в порядке объявления, с итоговыми типами |

Если `errors` пуст, все типы известны (`"error"` и `"?"` не встречаются). Это гарантия для HW4 и кодогенерации:
по `Function.params`, `returns`, `locals` строится таблица слотов, по `Expr.type` выбираются инструкции.

Текстовый вид: тип печатается после `:`.

```
Assign b  @5:5
  value: ArrayUpdate b : int[]  @5:5
    index: Num 0 : int  @5:7
    value: Num 42 : int  @5:12
...
locals:
  VarDef t int[]  @6:57
  VarDef cnt int  @9:16
```

JSON: у выражений появляется ключ `"type"`, у функций — `"locals"` (список `VarDef`).
Для обхода дерева есть `funny_ast.walk(node)` — все узлы в глубину.
