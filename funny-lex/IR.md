# IR Funny: трёхадресный код — формат и API для кодогенерации (HW4)

IR — это то, что получает кодогенератор под JVM (проект, T1). Строится из **аннотированного AST**
(HW3, без ошибок), потом оптимизируется.

```
AST + типы (HW3) ──► funny_irgen.generate ──► IRModule ──► funny_opt.optimize ──► IRModule ──► кодогенерация
                                                  │                                  │
                                                  └── funny_cfg.build_cfg ◄──────────┘  CFG, живость
                                                                                     funny_regalloc.allocate  раскраска
```

## 1. Модуль и функция

```
function sum(a: int[]) returns s: int        ← заголовок: параметры и результаты с типами
    locals i: int                            ← локальные переменные Funny (выведены в HW3)
    temps  t1: int, t2: bool, t3: int        ← временные, которые создал генератор
    s := 0                                   ← инструкции — с отступом
    i := 0
L1:                                          ← метки — без отступа
    t1 := length a
    t2 := i < t1
    if t2 goto L2
    goto L3
L2:
    t3 := load a[i]
    s := s + t3
    i := i + 1
    goto L1
L3:
    return s
end
```

* `IRModule.functions` — функции в порядке исходника. Формулы (`formula … => …`) в IR не попадают.
* У каждой функции:
  * `name`;
  * `params` — пары (имя, тип) в порядке объявления;
  * `returns` — пары (имя, тип) в порядке объявления;
  * `locals` — пары (имя, тип);
  * `temps` — словарь `{имя: тип}`;
  * `code` — список инструкций.
* **Типы**: `int`, `int[]`, `bool`. Тип `bool` бывает только у временных — результатов сравнений.
  В Funny нет переменных типа bool.
* **Имена**:
  * Временные называются `t1, t2, …`. Если в программе есть переменная с таким же именем, номер пропускается, так что временная не совпадёт с переменной Funny.
  * Метки называются `L1, L2, …`.
  * Метод `fn.is_temp(name)` отличает временную от переменной программы, а `fn.type_of(name)` даёт тип любой переменной.

## 2. Операнды

Операнд — это **переменная** (строка-имя) или **константа**: целое число (`int`) или `true`/`false`.
Константа может стоять везде, где значение **читается**: `x := 5`, `t := a + 1`, `if true goto L`,
`return 0`, `load a[3]`, `call f(1)`.
Записывать можно только в переменную.

## 3. Инструкции

| Текст | Класс (`funny_ir.py`) | JSON `op` | Пишет | Читает | Может упасть |
|---|---|---|---|---|---|
| `L:` | `Label(name)` | `label` | — | — | нет |
| `x := y` / `x := 5` | `Copy(dst, src)` | `copy` | x | y | нет |
| `x := y op z`, op ∈ `+ - * /` | `BinOp(dst, op, left, right)` | `binop` | x | y, z | `/` на 0 |
| `x := y op z`, op ∈ `== != < <= > >=` | `BinOp` (x типа bool) | `binop` | x | y, z | нет |
| `x := -y` | `UnOp(dst, "-", arg)` | `unop` | x | y | нет |
| `x := length a` | `Length(dst, array)` | `length` | x | a | нет |
| `x := load a[i]` | `Load(dst, array, index)` | `load` | x | a, i | i вне `[0, length a)` |
| `x := update(a, i, v)` | `Update(dst, array, index, value)` | `update` | x | a, i, v | i вне `[0, length a)` |
| `goto L` | `Goto(label)` | `goto` | — | — | нет |
| `if x goto L` | `IfGoto(cond, label)` | `if` | — | x | нет |
| `x1, …, xm := call f(a1, …, an)` | `Call(dsts, func, args)` | `call` | x1..xm | a1..an | что угодно |
| `return v1, …, vm` | `Return(values)` | `return` | — | v1..vm | нет |

Пояснения к таблице:

* **Арифметика — как у `int` в Java.**
  * 32 бита со знаком, переполнение по модулю 2³².
  * `/` отбрасывает дробную часть к нулю: `-7 / 2 = -3`.
  * `MIN / -1 = MIN`.
  * Деление на 0 — исключение.
* **`update` создаёт НОВЫЙ массив**, а старый `a` не меняется: массивы Funny неизменяемые.
  Присваивание `a[i] = v` превращается в `t := update(a, i, v); a := t`. После оптимизации это одна инструкция `a := update(a, i, v)`.
* **`if x goto L`** переходит на `L`, если `x == true`, а иначе выполняется следующая инструкция.
  Генератор всегда пишет пару `if t goto Lтогда; goto Lиначе`. Это одно ветвление на два направления, как в лекции 6.
  После оптимизаций второй `goto` может пропасть, если `Lиначе` идёт сразу следом.
* **`call`** вызывает функцию модуля. Число `dsts` равно числу `returns` вызываемой функции.
  Встроенная `length` — это не вызов, а отдельная инструкция `length`.
* **`return v1, …, vm`** — значения результатов в порядке `returns`.
  * Генератор пишет `return r1, …, rm`, то есть имена возвращаемых переменных.
  * После распространения копий вместо имени может стоять другая переменная или константа. Например, `g := x; return g` превращается в `return x`.
  * Return — всегда последняя инструкция функции; других выходов нет.
* **`assert` / `assume`** в IR не попадают: они нужны для верификации, а не для выполнения.

### JSON

`python funny.py file.funny --ir-json` печатает:

```json
{"functions": [{
  "name": "sum",
  "params":  [{"name": "a", "type": "int[]"}],
  "returns": [{"name": "s", "type": "int"}],
  "locals":  [{"name": "i", "type": "int"}],
  "temps":   [{"name": "t1", "type": "int"}, {"name": "t2", "type": "bool"}],
  "code": [
    {"op": "copy",   "dst": "s", "src": 0},
    {"op": "label",  "name": "L1"},
    {"op": "length", "dst": "t1", "array": "a"},
    {"op": "binop",  "dst": "t2", "operator": "<", "left": "i", "right": "t1"},
    {"op": "if",     "cond": "t2", "label": "L2"},
    {"op": "goto",   "label": "L3"},
    {"op": "load",   "dst": "t3", "array": "a", "index": "i"},
    {"op": "update", "dst": "b", "array": "b", "index": 0, "value": "t3"},
    {"op": "unop",   "dst": "t4", "operator": "-", "arg": "t3"},
    {"op": "call",   "dsts": ["q", "r"], "func": "divmod", "args": ["x", 2]},
    {"op": "return", "values": ["s"]}
  ]
}]}
```

Как читать операнды в JSON:

* строка — имя переменной;
* число — константа int;
* `true` / `false` — константа bool.

## 4. Как переводится Funny (шаблоны генератора)

| Funny | IR |
|---|---|
| `x = e;` | код для `e`, результат в операнде `o`; затем `x := o` |
| `x, y = f(a, b);` | `x, y := call f(a', b')` |
| `a[i] = v;` | `t := update(a, i', v'); a := t` |
| `if (c) S1 else S2` | `cond(c, L1, L2)`, потом `L1: S1`, `goto L3`, `L2: S2`, `L3:` |
| `if (c) S` | `cond(c, L1, L2)`, потом `L1: S`, `L2:` |
| `while (c) S` | `L1:`, `cond(c, L2, L3)`, потом `L2: S`, `goto L1`, `L3:` |
| конец функции | `return r1, …, rm` |

`cond(c, Lt, Lf)` — это условие, переведённое **прыжками** (jumping code):

* сравнение `a < b` даёт `t := a < b; if t goto Lt; goto Lf`;
* `not c` превращается в `cond(c, Lf, Lt)` — метки просто меняются местами;
* `c1 and c2` превращается в `cond(c1, Lm, Lf)`, затем `Lm:`, затем `cond(c2, Lt, Lf)`. Если c1 ложно, c2 не вычисляется;
* `c1 or c2` превращается в `cond(c1, Lt, Lm)`, затем `Lm:`, затем `cond(c2, Lt, Lf)`;
* `c1 -> c2` переводится как `not c1 or c2`;
* `true` / `false` превращаются в `goto Lt` / `goto Lf`.

Так `and`/`or` получают **короткое замыкание**, как в Java: в `b != 0 and a / b > 1` при `b == 0` деления нет.

## 5. CFG (`funny_cfg.py`)

`build_cfg(fn)` возвращает объект `CFG` с полями:

* `blocks` — блоки в порядке кода, первый из них входной;
* `entry` — входной блок;
* `exits()` — блоки, которые заканчиваются `return`.

У каждого блока `BasicBlock` есть:

* `name` — `B1`, `B2`, …;
* `instrs` — инструкции; если у блока есть метка, она первая;
* `succs` — список `[(имя, "true"|"false"|"")]`;
* `preds` — предшественники;
* `live_in`, `live_out` — живые переменные на входе и выходе, их заполняет `liveness(cfg)`.

Блок начинается («лидер»):

* с первой инструкции функции;
* с метки;
* с инструкции после `goto` / `if` / `return`.

Исключение: `goto` сразу после `if` остаётся в том же блоке. Пара `if … goto; goto` — одно ветвление.

## 6. Граф конфликтов (`funny_regalloc.py`)

`allocate(fn, color_all=False, regs=None)` возвращает объект `Interference` с полями:

* `nodes`;
* `edges` — пары `(a, b)`, где `a < b`;
* `colors` — словарь `{узел: 0, 1, …}`;
* `num_colors`;
* `spilled` — узлы с цветом ≥ regs;
* `is_valid()` — проверка, что раскраска правильная.

Узлы графа — временные. С `color_all` в граф попадают ещё результаты и локальные. Параметры не красятся, потому что их слоты задаёт соглашение о вызове.

## 7. Что нужно кодогенератору под JVM (план T1)

| IR | JVM |
|---|---|
| параметры | слоты `0..n-1` метода `static`; `int` → `I`, `int[]` → `ImmutableIntArray` |
| результаты: одно `int` | метод возвращает `I` |
| результаты: несколько | метод возвращает `int[]` (как в спецификации проекта), вызывающий распаковывает |
| временные одного цвета | один слот: номер слота = число параметров + число переменных + цвет |
| `x := y op z` | `iload y; iload z; iadd / isub / imul / idiv; istore x`. `idiv` сам бросает `ArithmeticException` при делении на 0 |
| `t := a < b; if t goto L1; goto L2` | `iload a; iload b; if_icmplt L1; goto L2`. Генератору лучше узнавать этот шаблон, а не хранить bool |
| `length`, `load`, `update` | вызовы `ImmutableIntArray.length / get / set`; последний возвращает новый объект |
| `call` | `invokestatic` |
| `return` | `ireturn` / `areturn`, а для нескольких значений — сборка `int[]` |

Чтобы получить IR в коде:

```python
from funny_semantic import analyze
from funny_irgen import generate
from funny_opt import optimize
from funny_regalloc import allocate

module, errors = analyze(text)            # HW3; при ошибках дальше не идём
ir = generate(module)                     # IR без оптимизаций
opt, report = optimize(ir, ["constprop", "algebra", "copies", "cse", "dce", "unreachable"])
for fn in opt.functions:
    slots = allocate(fn).colors           # временная -> номер ячейки
```
