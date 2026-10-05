#!/usr/bin/env python3
"""
lexgen.py — генератор лексера для языка Funny (HW1)

Что делает программа, по шагам:
    1. берёт список регулярных выражений токенов;
    2. строит из них НКА (алгоритм Томпсона);
    3. превращает НКА в ДКА (построение подмножеств);
    4. минимизирует ДКА (алгоритм Хопкрофта);
    5. сохраняет итоговую таблицу переходов в funny_dfa.json;
    6. прогоняет тесты.

Запуск:
    python3 lexgen.py                 — всё перечисленное выше
    python3 lexgen.py program.fun     — то же самое + разбить program.fun на токены
"""
import json
import sys

# 1. ТОКЕНЫ
# (имя, вид, регулярка). Вид: "token" — обычный, "skip" — выбросить, "error" — ошибка.
# Порядок важен: если две регулярки подходят под строку одной длины,
# побеждает та, что ВЫШЕ. Поэтому ключевые слова стоят раньше IDENT.

TOKENS = [
    ("WS",           "skip",  r"[ \t\r\n]+"),
    ("COMMENT",      "skip",  r"//([^\n]|[\x80-\xff])*"),
    ("KW_FUNCTION",  "token", r"function"),
    ("KW_RETURNS",   "token", r"returns"),
    ("KW_WHILE",     "token", r"while"),
    ("KW_IF",        "token", r"if"),
    ("KW_ELSE",      "token", r"else"),
    ("KW_ASSERT",    "token", r"assert"),
    ("KW_ASSUME",    "token", r"assume"),
    ("KW_INVARIANT", "token", r"invariant"),
    ("KW_LENGTH",    "token", r"length"),
    ("IDENT",        "token", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("INT",          "token", r"0|[1-9][0-9]*"),
    ("BAD_INT",      "error", r"0[0-9]+"),          
    ("EQ",           "token", r"=="),
    ("NE",           "token", r"!="),
    ("LE",           "token", r"<="),
    ("GE",           "token", r">="),
    ("LT",           "token", r"<"),
    ("GT",           "token", r">"),
    ("ASSIGN",       "token", r"="),
    ("PLUS",         "token", r"\+"),              
    ("MINUS",        "token", r"-"),
    ("STAR",         "token", r"\*"),
    ("SLASH",        "token", r"/"),
    ("LPAREN",       "token", r"\("),
    ("RPAREN",       "token", r"\)"),
    ("LBRACKET",     "token", r"\["),
    ("RBRACKET",     "token", r"\]"),
    ("LBRACE",       "token", r"{"),
    ("RBRACE",       "token", r"}"),
    ("COMMA",        "token", r","),
    ("SEMI",         "token", r";"),
    ("COLON",        "token", r":"),
]

TRAP = 0     # номер ловушки в ДКА
START = 1    # номер стартового состояния ДКА


# 2. РЕГУЛЯРКА -> НКА (Томпсон)
#
# НКА — это граф:
#   - символ None —  ε-стрелка
#   - accept[q] = номер токена, если в состоянии q заканчивается этот токен.
# Символ — это байт, число от 0 до 255.
#
# Каждая функция разбора возвращает пару (вход, выход) — номера первого и последнего
# состояния построенной части графа. 

class NFA:
    def __init__(self):
        self.count = 0        # сколько состояний создано
        self.edges = []       # стрелки: (откуда, куда, символ или None)
        self.accept = {}      # состояние -> номер токена

    def new_state(self):
        self.count += 1
        return self.count - 1

    def add_edge(self, frm, to, symbol=None):
        self.edges.append((frm, to, symbol))


class RegexParser:
    """Разбирает одну регулярку и достраивает НКА.

    Уровни (по увеличению приоритета)
        alt     — выбор:       a|b
        concat  — конкатенация:     ab
        repeat  — повторение:  a*  a+  a?
        atom    — один символ, [класс] или (скобки)
    """

    def __init__(self, nfa, regex, token_name):
        self.nfa = nfa
        self.re = regex
        self.pos = 0
        self.token_name = token_name

    def error(self, msg):
        sys.exit(f"ошибка в регулярке токена {self.token_name}, позиция {self.pos}: {msg}")

    def peek(self):
        """Текущий символ регулярки (или None, если она кончилась)."""
        return self.re[self.pos] if self.pos < len(self.re) else None

    def read_char(self):
        c = self.peek()
        if c is None:
            self.error("неожиданный конец регулярки")
        self.pos += 1
        if c != "\\":
            if ord(c) >= 128:
                self.error("не-ASCII символ ")
            return ord(c)
        c = self.peek()
        if c is None:
            self.error("\\ в конце регулярки")
        self.pos += 1
        if c == "n":
            return ord("\n")
        if c == "t":
            return ord("\t")
        if c == "r":
            return ord("\r")
        if c == "x":
            hex_digits = self.re[self.pos:self.pos + 2]
            self.pos += 2
            return int(hex_digits, 16)
        return ord(c)

    def chars_piece(self, symbols):
        """Стрелка с символом:  вход --c--> выход  для каждого c из symbols."""
        start, end = self.nfa.new_state(), self.nfa.new_state()
        for c in sorted(symbols):
            self.nfa.add_edge(start, end, c)
        return start, end

    def parse(self):
        start, end = self.parse_alt()
        if self.peek() is not None:
            self.error("лишняя )")
        return start, end

    # --- alt выбор:  a | b | c ---------------------------------------------------
    def parse_alt(self):
        start, end = self.parse_concat()
        while self.peek() == "|":
            self.pos += 1
            start2, end2 = self.parse_concat()
            new_start, new_end = self.nfa.new_state(), self.nfa.new_state()
            self.nfa.add_edge(new_start, start)     # развилка: либо первый вариант,
            self.nfa.add_edge(new_start, start2)    #           либо второй
            self.nfa.add_edge(end, new_end)         # оба выхода сходятся в один
            self.nfa.add_edge(end2, new_end)
            start, end = new_start, new_end
        return start, end

    # --- concat:  abc ------------------------------------------------------
    def parse_concat(self):
        pieces = []
        while self.peek() is not None and self.peek() not in "|)":
            pieces.append(self.parse_repeat())
        if not pieces:                              # пусто, например в (a|)
            start, end = self.nfa.new_state(), self.nfa.new_state()
            self.nfa.add_edge(start, end)
            return start, end
        for (_, end1), (start2, _) in zip(pieces, pieces[1:]):
            self.nfa.add_edge(end1, start2)         # выход куска -> вход следующего
        return pieces[0][0], pieces[-1][1]

    # --- repeat повторение:  a*  a+  a? -----------------------------------------------
    def parse_repeat(self):
        start, end = self.parse_atom()
        while self.peek() is not None and self.peek() in "*+?":
            q = self.peek()
            self.pos += 1
            new_start, new_end = self.nfa.new_state(), self.nfa.new_state()
            self.nfa.add_edge(new_start, start)     # зайти внутрь
            self.nfa.add_edge(end, new_end)         # выйти наружу
            if q in "*?":
                self.nfa.add_edge(new_start, new_end)   # можно пропустить (0 раз)
            if q in "*+":
                self.nfa.add_edge(end, start)           # можно повторить ещё раз
            start, end = new_start, new_end
        return start, end

    # --- atom:  символ, [класс], (скобки) -----------------------------------
    def parse_atom(self):
        c = self.peek()
        if c == "(":
            self.pos += 1
            start, end = self.parse_alt()
            if self.peek() != ")":
                self.error("нет закрывающей )")
            self.pos += 1
            return start, end
        if c == "[":
            self.pos += 1
            return self.chars_piece(self.parse_class())
        if c in ("*", "+", "?"):
            self.error("*, + или ? без того, что повторять")
        return self.chars_piece({self.read_char()})

	# парсим [что внутри скобок]
    def parse_class(self):
        """[abc], [a-z], [^\\n]. Мы уже прочитали '['. Возвращает множество кодов символов."""
        symbols = set()
        negate = False
        if self.peek() == "^":
            negate = True
            self.pos += 1
        while self.peek() != "]":
            if self.peek() is None:
                self.error("нет закрывающей ]")
            lo = self.read_char()
            hi = lo
            if self.peek() == "-" and self.pos + 1 < len(self.re) and self.re[self.pos + 1] != "]":
                self.pos += 1               # пропустить '-'
                hi = self.read_char()
            symbols.update(range(lo, hi + 1))
        self.pos += 1                       # пропустить ']'
        if negate:
            # [^...] = все ASCII-символы, кроме перечисленных.
            # Байты 128..255 сюда не попадают — без явного [\x80-\xff] они уходят в ловушку.
            symbols = set(range(128)) - symbols
        return symbols


def build_nfa():
    print("\n== Шаг 1. Регулярки -> НКА (Томпсон) ==")
    nfa = NFA()
    nfa_start = nfa.new_state()                     # общий старт
    print(f"    общий старт: состояние {nfa_start}")
    for i, (name, kind, regex) in enumerate(TOKENS):
        before = nfa.count
        start, end = RegexParser(nfa, regex, name).parse()
        nfa.accept[end] = i                         # здесь заканчивается токен i
        nfa.add_edge(nfa_start, start)              # общий старт --ε--> вход токена
        print(f"    {name:<13} +{nfa.count - before:2} состояний "
              f"(вход {start:3}, выход {end:3}), всего {nfa.count:3}")
    print(f"ИТОГ шага 1: НКА — {nfa.count} состояний, {len(nfa.edges)} стрелок")
    return nfa, nfa_start


# ============================================================================
# 3. НКА -> ДКА (построение подмножеств)
#
# ДКА хранится как словарь:
#   dfa["next"][s][c]  — куда перейти из состояния s по байту c (таблица n x 256)
#   dfa["accept"][s]   — номер токена, который принимает состояние s, или -1
# ============================================================================

def build_dfa(nfa, nfa_start):
    # Разложим стрелки НКА для быстрого поиска
    eps = {}          # состояние -> список, куда ведут ε-стрелки
    by_symbol = {}    # (состояние, символ) -> список, куда ведут стрелки по символу
    for frm, to, symbol in nfa.edges:
        if symbol is None:
            eps.setdefault(frm, []).append(to)
        else:
            by_symbol.setdefault((frm, symbol), []).append(to)

    def eps_closure(states):
        """Множество states + все состояния, до которых можно дойти по ε-стрелкам."""
        result = set(states)
        stack = list(states)
        while stack:
            q = stack.pop()
            for r in eps.get(q, []):
                if r not in result:
                    result.add(r)
                    stack.append(r)
        return frozenset(result)    # frozenset — неизменяемое множество, его можно класть в словарь

    def move(states, c):
        """Куда ведут стрелки с символом c из состояний states."""
        result = set()
        for q in states:
            result.update(by_symbol.get((q, c), []))
        return result

    sets = [frozenset(), eps_closure({nfa_start})]   # 0 — пустое множество (ловушка), 1 — старт
    number_of = {sets[0]: TRAP, sets[1]: START}      # множество -> номер состояния ДКА
    next_table = []

    s = 0
    while s < len(sets):            # sets растёт по ходу: новые состояния тоже обработаются
        row = []
        for c in range(256):
            target = eps_closure(move(sets[s], c))
            if target not in number_of:              # такого множества ещё не было — новое состояние
                number_of[target] = len(sets)
                sets.append(target)
            row.append(number_of[target])
        next_table.append(row)
        s += 1

    # Что принимает состояние: если в множестве концы нескольких токенов — берём
    # токен с меньшим номером (он выше в списке = приоритетнее).
    accept = []
    for states in sets:
        tokens_here = [nfa.accept[q] for q in states if q in nfa.accept]
        accept.append(min(tokens_here) if tokens_here else -1)

    if accept[START] >= 0:
        sys.exit("ошибка: какой-то токен принимает пустую строку")

    accepting = sum(1 for a in accept if a >= 0)
    print("\n== Шаг 2. НКА -> ДКА (построение подмножеств) ==")
    print("    состояние 0 — пустое множество (ловушка), состояние 1 — старт")
    print(f"    принимающих состояний: {accepting}, непринимающих: {len(sets) - accepting}")
    print(f"ИТОГ шага 2: ДКА — {len(sets)} состояний (включая ловушку)")
    return {"next": next_table, "accept": accept}


# 4. МИНИМИЗАЦИЯ (Хопкрофт)
#
# Правило: внутри группы все состояния по каждому символу должны идти В ОДНУ И ТУ ЖЕ
# группу. Если идут в разные — группу режем. Повторяем, пока режется.

def minimize(dfa):
    nxt, acc = dfa["next"], dfa["accept"]
    n = len(acc)

    # --- Шаг 1: начальные группы — по тому, какой токен принимается ---
    group_by_accept = {}
    group = []                          # group[q] = номер группы состояния q
    for q in range(n):
        if acc[q] not in group_by_accept:
            group_by_accept[acc[q]] = len(group_by_accept)
        group.append(group_by_accept[acc[q]])
    group_count = len(group_by_accept)
    size = [group.count(g) for g in range(group_count)]

    print("\n== Шаг 3. Минимизация (Хопкрофт) ==")
    print(f"    начальных групп (по тому, что принимают): {group_count}")

    # --- Шаг 2: в очередь — все группы, кроме самой большой ---
    largest = size.index(max(size))
    queue = [g for g in range(group_count) if g != largest]
    in_queue = set(queue)
    splits = 0

    # --- Шаг 3: пока очередь не пуста — режем ---
    while queue:
        A = queue.pop()                                  # достали группу A
        in_queue.discard(A)
        members_of_A = {q for q in range(n) if group[q] == A}

        for c in range(256):
            # кто по символу c приходит в A — разложим их по их группам
            came_to_A = {}                               # группа -> её члены, которые приходят в A
            for q in range(n):
                if nxt[q][c] in members_of_A:
                    came_to_A.setdefault(group[q], []).append(q)

            for Y, yes in came_to_A.items():
                if len(yes) == size[Y]:
                    continue                             # приходят все — группа однородна, не режем
                # приходят не все — режем: кто приходит, переезжает в новую группу Z
                Z = group_count
                group_count += 1
                splits += 1
                for q in yes:
                    group[q] = Z
                size.append(len(yes))
                size[Y] -= len(yes)

                if Y in in_queue:                        # Y и так ждёт проверки — добавим и Z
                    queue.append(Z)
                    in_queue.add(Z)
                else:                                    # иначе — только меньший кусок
                    smaller = Z if size[Z] <= size[Y] else Y
                    queue.append(smaller)
                    in_queue.add(smaller)

    # --- Шаг 4: каждая группа становится одним состоянием ---
    new_id = {group[TRAP]: 0}                            # группа ловушки -> 0
    new_id.setdefault(group[START], 1)                   # группа старта  -> 1
    for q in range(n):
        new_id.setdefault(group[q], len(new_id))         # остальные — по порядку
    count = len(new_id)

    new_next = [None] * count
    new_accept = [None] * count
    for q in range(n):
        # члены одной группы ведут себя одинаково, поэтому неважно, чьи переходы брать
        s = new_id[group[q]]
        new_accept[s] = acc[q]
        new_next[s] = [new_id[group[t]] for t in nxt[q]]

    print(f"    разрезов сделано: {splits}  ({len(group_by_accept)} + {splits} = {group_count} групп)")
    print(f"    склеено состояний: {n - count}  ({n} -> {count})")
    print(f"ИТОГ шага 3: минимальный ДКА — {count} состояний (включая ловушку)")
    return {"next": new_next, "accept": new_accept}


# Хелперы для тестов
# Текст подаётся как bytes (байты), потому что таблица — по байтам 0..255.

def match(dfa, data):
    """Прогнать ВСЮ строку целиком. Ответ: имя токена, 'REJECT' (не токен) или 'TRAP' (ловушка)."""
    state = START
    for byte in data:
        state = dfa["next"][state][byte]
        if state == TRAP:
            return "TRAP"
    if dfa["accept"][state] >= 0:
        return TOKENS[dfa["accept"][state]][0]
    return "REJECT"


def lex(dfa, data):
    """Лексер: разрезать текст на токены (правило «самый длинный кусок»).
    Возвращает список пар (имя токена, кусок текста). Пробелы и комментарии выброшены."""
    result = []
    pos = 0
    while pos < len(data):
        state = START
        best_token, best_end = -1, pos
        for i in range(pos, len(data)):
            state = dfa["next"][state][data[i]]
            if state == TRAP:
                break                               # дальше токен не продолжится
            if dfa["accept"][state] >= 0:           # здесь кончается токен — запомнить
                best_token, best_end = dfa["accept"][state], i + 1

        if best_token < 0:                          # отсюда не начинается ни один токен
            result.append(("ERROR", data[pos:pos + 1]))
            pos += 1
            continue
        name, kind, _ = TOKENS[best_token]
        if kind != "skip":
            result.append((name, data[pos:best_end]))
        pos = best_end
    return result


# 6. сохранение таблицы

def export_table(dfa, path):
    table = {
        "start": START,
        "trap": TRAP,
        "tokens": [{"name": name, "kind": kind} for name, kind, _ in TOKENS],
        "accept": dfa["accept"],        # accept[состояние] = номер токена или -1
        "next": dfa["next"],            # next[состояние][байт] = следующее состояние
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table, f)
    print("\n== Шаг 4. Таблица ==")
    print(f"    {path}: таблица {len(dfa['accept'])} состояний x 256 байтов")


# 7. ТЕСТЫ
# Тест = (вид, что подать, что должно получиться). 
#   "match" — вся строка целиком: имя токена, "REJECT" или "TRAP";
#   "lex"   — лексер: имена токенов через пробел, "<none>" если токенов нет.
# Строки с русскими буквами переводятся в байты UTF-8; b"..." — сразу байты.

TESTS = [
    # пустая строка
    ("match", "", "REJECT"),
    ("lex", "", "<none>"),

    # только пробелы, табы, CRLF
    ("match", " ", "WS"), ("match", "\t\t", "WS"), ("match", "\r\n", "WS"), ("match", " \t\r\n ", "WS"),
    ("lex", "   ", "<none>"), ("lex", "\t", "<none>"), ("lex", "\r\n\r\n", "<none>"),
    ("lex", "a\r\nb", "IDENT IDENT"),

    # числа: 0 — можно, 00 и 01 — нельзя
    ("match", "0", "INT"), ("match", "10", "INT"), ("match", "1234567890", "INT"),
    ("match", "00", "BAD_INT"), ("match", "01", "BAD_INT"), ("match", "007", "BAD_INT"),
    ("lex", "0", "INT"), ("lex", "00", "BAD_INT"), ("lex", "01", "BAD_INT"),
    ("lex", "0 1", "INT INT"), ("lex", "-1", "MINUS INT"), ("lex", "12ab", "INT IDENT"),

    # идентификаторы с _
    ("match", "_", "IDENT"), ("match", "_x1", "IDENT"), ("match", "x_", "IDENT"),
    ("match", "snake_case_42", "IDENT"), ("match", "__init__", "IDENT"),
    ("lex", "_a _ b_", "IDENT IDENT IDENT"),

    # ключевые слова и похожие на них идентификаторы
    ("match", "function", "KW_FUNCTION"), ("match", "returns", "KW_RETURNS"),
    ("match", "while", "KW_WHILE"), ("match", "if", "KW_IF"), ("match", "else", "KW_ELSE"),
    ("match", "assert", "KW_ASSERT"), ("match", "assume", "KW_ASSUME"),
    ("match", "invariant", "KW_INVARIANT"), ("match", "length", "KW_LENGTH"),
    ("match", "functions", "IDENT"), ("match", "func", "IDENT"), ("match", "Function", "IDENT"),
    ("match", "iff", "IDENT"), ("match", "if_", "IDENT"), ("match", "_if", "IDENT"), ("match", "in", "IDENT"),
    ("lex", "if else", "KW_IF KW_ELSE"), ("lex", "ifelse", "IDENT"),
    ("lex", "function f() returns r", "KW_FUNCTION IDENT LPAREN RPAREN KW_RETURNS IDENT"),

    # разделители
    ("match", "(", "LPAREN"), ("match", ")", "RPAREN"), ("match", "[", "LBRACKET"),
    ("match", "]", "RBRACKET"), ("match", "{", "LBRACE"), ("match", "}", "RBRACE"),
    ("match", ",", "COMMA"), ("match", ";", "SEMI"), ("match", ":", "COLON"),
    ("lex", "()[]{},;:", "LPAREN RPAREN LBRACKET RBRACKET LBRACE RBRACE COMMA SEMI COLON"),

    # операторы
    ("match", "+", "PLUS"), ("match", "-", "MINUS"), ("match", "*", "STAR"), ("match", "/", "SLASH"),
    ("match", "==", "EQ"), ("match", "!=", "NE"), ("match", "<=", "LE"), ("match", ">=", "GE"),
    ("match", "<", "LT"), ("match", ">", "GT"), ("match", "=", "ASSIGN"),
    ("match", "!", "REJECT"), ("match", "===", "TRAP"),
    ("lex", "a==b", "IDENT EQ IDENT"), ("lex", "===", "EQ ASSIGN"), ("lex", "<==", "LE ASSIGN"),
    ("lex", "x<=y>=z!=w", "IDENT LE IDENT GE IDENT NE IDENT"), ("lex", "!", "ERROR"),

    # двоеточие
    ("lex", "main() returns r:int", "IDENT LPAREN RPAREN KW_RETURNS IDENT COLON IDENT"),

    # комментарии до конца строки (в том числе с русскими буквами)
    ("match", "//", "COMMENT"), ("match", "// if 01 @#", "COMMENT"), ("match", "// x\n", "TRAP"),
    ("match", "// привет", "COMMENT"),
    ("lex", "// comment", "<none>"), ("lex", "x // c\ny", "IDENT IDENT"),
    ("lex", "x // c\r\ny", "IDENT IDENT"), ("lex", "a/b", "IDENT SLASH IDENT"), ("lex", "a///b", "IDENT"),
    ("lex", "x = 1 // привет\ny", "IDENT ASSIGN INT IDENT"),

    # не-ASCII вне комментария и непокрытые символы -> ловушка
    ("match", b"\x80", "TRAP"), ("match", b"\xff", "TRAP"), ("match", "п", "TRAP"), ("match", "@", "TRAP"),
    ("lex", "п", "ERROR ERROR"),                    # «п» в UTF-8 — это 2 байта
    ("lex", "x = 1 @ 2", "IDENT ASSIGN INT ERROR INT"), ("lex", "a#b", "IDENT ERROR IDENT"),

    # небольшая программа
    ("lex", "while (i < n) invariant (i <= n) { s = s + a[i]; i = i + 1; }",
     "KW_WHILE LPAREN IDENT LT IDENT RPAREN KW_INVARIANT LPAREN IDENT LE IDENT RPAREN "
     "LBRACE IDENT ASSIGN IDENT PLUS IDENT LBRACKET IDENT RBRACKET SEMI "
     "IDENT ASSIGN IDENT PLUS INT SEMI RBRACE"),
]


def expected_single_char(c):
    """Чем должен быть каждый отдельный байт — правило написано руками, независимо от автомата."""
    ch = chr(c)
    if ch.isascii() and (ch.isalpha() or ch == "_"):
        return "IDENT"
    if ch.isascii() and ch.isdigit():
        return "INT"
    single = {
        " ": "WS", "\t": "WS", "\r": "WS", "\n": "WS",
        "(": "LPAREN", ")": "RPAREN", "[": "LBRACKET", "]": "RBRACKET",
        "{": "LBRACE", "}": "RBRACE", ",": "COMMA", ";": "SEMI", ":": "COLON",
        "+": "PLUS", "-": "MINUS", "*": "STAR", "/": "SLASH",
        "<": "LT", ">": "GT", "=": "ASSIGN",
        "!": "REJECT",              # начало != , но сам по себе не токен
    }
    return single.get(ch, "TRAP")   # всё остальное, включая байты 128..255


def to_bytes(text):
    return text if isinstance(text, bytes) else text.encode("utf-8")


def run_tests(dfa_raw, dfa_min):
    print("\n== Тесты (каждый — на ДКА до и после минимизации) ==")
    failed = 0
    for kind, given, expected in TESTS:
        data = to_bytes(given)
        if kind == "match":
            got_raw, got_min = match(dfa_raw, data), match(dfa_min, data)
        else:
            got_raw = " ".join(name for name, _ in lex(dfa_raw, data)) or "<none>"
            got_min = " ".join(name for name, _ in lex(dfa_min, data)) or "<none>"
        ok = got_min == expected and got_raw == expected
        failed += not ok
        line = f"[{'PASS' if ok else 'FAIL'}] {kind:<5} {given!r} => {got_min}"
        if not ok:
            line += f"   (ожидалось: {expected}, до минимизации: {got_raw})"
        print(line)

    # Покрытие алфавита: каждый из 256 байтов по отдельности
    bad = 0
    for c in range(256):
        expected = expected_single_char(c)
        got_raw, got_min = match(dfa_raw, bytes([c])), match(dfa_min, bytes([c]))
        if got_min != expected or got_raw != expected:
            print(f"[FAIL] байт 0x{c:02x}: ожидалось {expected}, получено {got_min}")
            bad += 1
    print(f"[{'FAIL' if bad else 'PASS'}] каждый из 256 байтов по отдельности "
          f"(0..127 ASCII, 128..255 не-ASCII)")

    failed += bad > 0
    print(f"\nИтог: {len(TESTS)} тестов + проверка 256 байтов, провалено: {failed}")
    return failed


# 8. MAIN
def main():
    print("== Регулярные выражения ==")
    for i, (name, kind, regex) in enumerate(TOKENS):
        print(f"{i:2}  {name:<13} {kind:<6} {regex}")

    nfa, nfa_start = build_nfa()
    dfa_raw = build_dfa(nfa, nfa_start)
    dfa_min = minimize(dfa_raw)
    export_table(dfa_min, "funny_dfa.json")

    print("\n== Сводка размеров ==")
    print(f"НКА:                     {nfa.count} состояний, {len(nfa.edges)} стрелок")
    print(f"ДКА до минимизации:      {len(dfa_raw['accept'])} состояний (включая ловушку)")
    print(f"ДКА после минимизации:   {len(dfa_min['accept'])} состояний (включая ловушку)")
    print("\n== Ловушка ==")
    print(f"Состояние {TRAP}: ничего не принимает, из него все переходы ведут в него же.")
    print("Любой символ, которого не ждёт ни одна регулярка, ведёт туда. Байты 128..255")
    print("(не-ASCII) ведут в ловушку из любого состояния, кроме тела комментария //.")

    failed = run_tests(dfa_raw, dfa_min)

    # Если передан файл — разобрать его на токены
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, "rb") as f:
            data = f.read()
        print(f"\n== Токены файла {path} ==")
        for name, piece in lex(dfa_min, data):
            print(f"{name:<13} {piece.decode('utf-8', errors='replace')}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
