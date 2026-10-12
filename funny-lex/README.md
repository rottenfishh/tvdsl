# Funny: лексер (HW1) и парсер (HW2)

Нужен только Python 3 (3.8+), ничего устанавливать не надо.

## Быстрый старт

```sh
python funny.py tests/good/06_arrays.funny            # AST деревом
python funny.py tests/good/06_arrays.funny --json     # AST в JSON
python funny.py tests/good/06_arrays.funny --tokens   # токены с позициями
python funny.py tests/bad/04_unclosed_paren.funny     # пример с ошибками
python run_tests.py                                   # все тесты HW2
python lexgen.py                                      # пересобрать funny_dfa.json + тесты HW1
```

`funny_dfa.json` уже собран. `lexgen.py` нужно запускать только после изменения списка токенов.

## Файлы

| Файл | Что это |
|---|---|
| `lexgen.py` | HW1: регулярки → НКА → ДКА → минимальный ДКА → `funny_dfa.json` (в HW2 добавлены токены) |
| `funny_dfa.json` | таблица минимального ДКА (результат HW1) |
| `funny_lexer.py` | лексер P02: режет текст по таблице ДКА, токены с позициями (строка, столбец) |
| `funny_ast.py` | узлы AST + печать в JSON и деревом |
| `funny_parser.py` | **парсер HW2**: LL(1), рекурсивный спуск, режим паники, обессахаривание `a[i] = v` |
| `funny.py` | командная строка |
| `run_tests.py` | тесты HW2 |
| `tests/good/` | позитивные программы + эталонные AST (`*.ast`) |
| `tests/bad/` | негативные программы + ожидаемые ошибки (`*.err`) |
| `tests/course/` | примеры из репозитория курса (`project/examples`) |
| `grammar.txt` | **финальная грамматика**: EBNF, приоритеты, FIRST/FOLLOW, преобразования, отклонения от funny.ru.md |
| `AST.md` | формат AST и API для следующих HW |
| `HW2_EXPLAINED.md` | подробное объяснение кода |
| `program.fun` | демо-файл HW1 (с ошибками, специально) |

## Пример

Вход (`tests/good/06_arrays.funny`, фрагмент):

```
setfirst(a:int[]) requires length(a) > 1 returns b:int[], h:int {
    ...
    b[0] = 42;               // b = ArrayUpdate(b, 0, 42)
```

Выход `python funny.py tests/good/06_arrays.funny` (фрагмент):

```
Module  @1:1
  items:
    Function setfirst  @2:1
      params:
        VarDef a int[]  @2:10
      requires: Binary >  @2:38
        left: Call length  @2:28
          args:
            Var a  @2:35
        right: Num 1  @2:40
      ...
          Assign b  @5:5
            value: ArrayUpdate b  @5:5
              index: Num 0  @5:7
              value: Num 42  @5:12
```

Ошибки (`python funny.py tests/bad/04_unclosed_paren.funny`). Парсер восстанавливается после первой ошибки и находит вторую:

```
tests/bad/04_unclosed_paren.funny:2:15: ошибка: ожидалась ')' после условия, а встретилось '{'
        if (r > 0 {
                  ^
tests/bad/04_unclosed_paren.funny:5:15: ошибка: ожидалась ')', а встретилось ';'
        r = (1 + 2;
                  ^
ошибок: 2
```

Код выхода `funny.py`: 0, если ошибок нет, и 1, если есть.

## HW2: что сделано

| Требование | Где |
|---|---|
| Ветка LL(1), рекурсивный спуск | `funny_parser.py`: одна функция `parse_*` на правило грамматики |
| Грамматика приведена к LL(1), приоритеты и ассоциативность зафиксированы | `grammar.txt`, разделы 3–5 |
| Лексер из P02 на результатах HW1, позиции токенов | `funny_lexer.py` читает `funny_dfa.json` |
| Вывод AST (текст и JSON) | `funny.py`, `funny_ast.py`, формат в `AST.md` |
| Режим паники, читаемые сообщения с позицией | `funny_parser.py` (`recover_statement`, `recover_definition`) |
| Функции с `returns`, `requires`/`ensures`, `=`, `if`, `while`, блоки, `assert`/`assume` | весь `funny_parser.py`; тесты `tests/good/01–10` |
| `a[i]` и `a[i] = v` как сахар для функционального копирования | `parse_assignment` → `Assign(a, ArrayUpdate(a, i, v))` |
| Сверх минимума | формулы, кванторы `forall`/`exists`, `uses`, присваивание кортежа `x, y = f(...)`, `length` |
| Отклонения от funny.ru.md задокументированы | `grammar.txt`, раздел 7 |
| Тесты: позитивные, негативные, snapshot AST, «не зацикливается» | `run_tests.py`: 81 проверка (подробнее ниже) |

### Тесты

```sh
python run_tests.py            # прогнать
python run_tests.py --update   # перезаписать эталоны .ast/.err (после проверки вывода глазами!)
```

1. Лексер: виды токенов, позиции, лексические ошибки.
2. `tests/good` (10 программ): разбираются без ошибок, AST совпадает с эталоном `*.ast`.
3. `tests/bad` (15 программ): ошибки совпадают с `*.err`. Есть пустой ввод, файл из одних комментариев,
   незакрытые `(` и `{`, лишние токены, неверные операторы (`**`, `===`, `=>`, `a < b < c`, `!`),
   ошибки лексера, ошибки в заголовках, вызов функции как оператор, несколько ошибок в одном файле.
4. `tests/course` (42 примера курса): `good_*` разбираются; `bad_missing_semicolon` и `bad_missing_paren`
   дают синтаксическую ошибку. `step12/good_formulas_sorted` пишет импликацию не-ASCII символом `→`
   вместо `->` и даёт лексическую ошибку: пример расходится со спецификацией. Остальные `bad_*` синтаксически правильны: в них ошибки имён и типов, это HW3.
5. Устойчивость: 3332 испорченных вариантов хороших программ (без одного токена или обрезанные).
   Парсер всегда завершается без падения и зависания. Отдельно проверяются 3000 вложенных скобок.

Добавить тест: положить `.funny` в `tests/good` или `tests/bad` и запустить `run_tests.py`. Эталон создастся сам; его нужно проверить.

---

## HW1. Лексер Funny на Python: регулярки → НКА → ДКА → минимальный ДКА

```sh
python lexgen.py               # шаги построения, размеры, тесты; сохраняет funny_dfa.json
python lexgen.py program.fun   # то же самое + разбивает program.fun на токены
```

### Что внутри `lexgen.py` (разделы идут по порядку алгоритма)

1. `TOKENS` — список регулярок (приоритет = порядок в списке).
2. `NFA`, `RegexParser`, `build_nfa` — регулярка → НКА (Томпсон).
3. `build_dfa` — НКА → ДКА (построение подмножеств).
4. `minimize` — минимизация Хопкрофта.
5. `match`, `lex` — как пользоваться таблицей.
6. `export_table` — запись таблицы в `funny_dfa.json`.
7. `TESTS`, `expected_single_char`, `run_tests` — тесты.

### Результат

- `funny_dfa.json` — итоговая таблица: `start`, `trap`, `tokens`, `accept[состояние]`,
  `next[состояние][байт]`.
- Размеры (после добавления токенов в HW2): НКА 305 состояний, ДКА 127, минимальный ДКА **123** (с ловушкой).
  До HW2 было 193 / 82 / 78.
- Ловушка: состояние 0. Не-ASCII байты ведут в неё из любого состояния, кроме тела комментария.
- Тесты: 120 тестов + проверка каждого из 256 байтов, на ДКА до и после минимизации.

### Добавлено в HW2

Ключевые слова `requires ensures uses int true false not and or forall exists` и символы
`->` (ARROW), `=>` (DARROW), `|` (PIPE). Без них нельзя разобрать предикаты, формулы и кванторы.
В `TOKENS` эти строки помечены «добавлено в HW2».

### Как добавить тест

Допишите строку в список `TESTS`:

```python
("match", "05", "BAD_INT"),
("lex", "if(a<=b)", "KW_IF LPAREN IDENT LE IDENT RPAREN"),
```
