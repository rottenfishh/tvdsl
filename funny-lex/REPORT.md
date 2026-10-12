# Отчёт HW1: регулярные выражения → минимальный ДКА (язык Funny)

## 1. Регулярные выражения

Источник токенов: спецификация языка `funny.ru.md`  и требования HW1.
Приоритет — порядок в списке: при совпадении длины выигрывает токен выше (ключевые слова раньше `IDENT`).
`skip`-токены (WS, COMMENT) лексер выбрасывает.

| № | токен | вид | регулярка |
|---:|---|---|---|
| 0 | WS | skip | `[ \t\r\n]+` |
| 1 | COMMENT | skip | `//([^\n]\|[\x80-\xff])*` |
| 2 | KW_FUNCTION | token | `function` |
| 3 | KW_RETURNS | token | `returns` |
| 4 | KW_WHILE | token | `while` |
| 5 | KW_IF | token | `if` |
| 6 | KW_ELSE | token | `else` |
| 7 | KW_ASSERT | token | `assert` |
| 8 | KW_ASSUME | token | `assume` |
| 9 | KW_INVARIANT | token | `invariant` |
| 10 | KW_LENGTH | token | `length` |
| 11 | KW_REQUIRES | token | `requires` |
| 12 | KW_ENSURES | token | `ensures` |
| 13 | KW_USES | token | `uses` |
| 14 | KW_INT | token | `int` |
| 15 | KW_TRUE | token | `true` |
| 16 | KW_FALSE | token | `false` |
| 17 | KW_NOT | token | `not` |
| 18 | KW_AND | token | `and` |
| 19 | KW_OR | token | `or` |
| 20 | KW_FORALL | token | `forall` |
| 21 | KW_EXISTS | token | `exists` |
| 22 | IDENT | token | `[A-Za-z_][A-Za-z0-9_]*` |
| 23 | INT | token | `0\|[1-9][0-9]*` |
| 24 | BAD_INT | error | `0[0-9]+` |
| 25 | EQ | token | `==` |
| 26 | NE | token | `!=` |
| 27 | LE | token | `<=` |
| 28 | GE | token | `>=` |
| 29 | LT | token | `<` |
| 30 | GT | token | `>` |
| 31 | ASSIGN | token | `=` |
| 32 | IMPLIES | token | `->` |
| 33 | DEFINES | token | `=>` |
| 34 | PLUS | token | `\+` |
| 35 | MINUS | token | `-` |
| 36 | STAR | token | `\*` |
| 37 | SLASH | token | `/` |
| 38 | LPAREN | token | `\(` |
| 39 | RPAREN | token | `\)` |
| 40 | LBRACKET | token | `\[` |
| 41 | RBRACKET | token | `\]` |
| 42 | LBRACE | token | `{` |
| 43 | RBRACE | token | `}` |
| 44 | COMMA | token | `,` |
| 45 | SEMI | token | `;` |
| 46 | COLON | token | `:` |
| 47 | BAR | token | `\\|` |

## 2. Размеры автоматов

| автомат | состояний |
|---|---:|
| НКА (Томпсон) | 305 (710 стрелок) |
| ДКА после построения подмножеств (с ловушкой) | 127 |
| минимальный ДКА, Хопкрофт (с ловушкой) | **123** |

## 3. Ловушка

- Состояние 0 — ловушка: ничего не принимает, все переходы из него ведут в него же.
- Таблица полная: для каждого состояния и каждого из 256 байтов задан переход; любой переход,
  которого нет в регулярках, ведёт в ловушку.
- Символы вне алфавита (байты 128..255) ведут в ловушку из любого состояния, кроме тела комментария `//`.
- Лексер: если с текущей позиции не начинается ни один токен, он выдаёт `ERROR` и пропускает один байт.

## 4. Тесты

- 134 тестов (`TESTS` в `lexgen.py`): вход + ожидаемый результат; каждый прогоняется на ДКА
  до и после минимизации.
- Все обязательные сценарии HW1: пустая строка; пробелы/табы/CRLF; `0`, `00`, `01`; идентификаторы с `_`;
  ключевые слова; операторы и разделители; комментарии; не-ASCII → ловушка.
- Покрытие алфавита: каждый из 256 байтов проверяется отдельно по правилу `expected_single_char`.

## 5. Экспорт

`funny_dfa.json`: `start`, `trap`, `tokens` (имя, вид), `accept[состояние]`, `next[состояние][байт]` —
подключается в лексер проекта вместе с функцией `lex` из `lexgen.py`.
