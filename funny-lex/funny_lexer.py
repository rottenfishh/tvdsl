"""
funny_lexer.py — лексер Funny для парсера (P02 / HW2).

Берём готовую таблицу минимального ДКА
из funny_dfa.json (её строит lexgen.py из HW1) и режем текст на токены
по правилу «самый длинный кусок» — так же, как lex() в lexgen.py.

Отличия от lex() из HW1:
    - у каждого токена есть позиция (строка и столбец, с 1);
    - ошибки не превращаются в токены, а собираются в отдельный список;
    - в конце всегда стоит токен EOF.

Использование:
    tokens, errors = tokenize("r = a + 1;")
    tokens[0]  ->  Token(kind='IDENT', text='r', line=1, col=1)
"""
import json
import os
from dataclasses import dataclass

TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "funny_dfa.json")


@dataclass
class Token:
    kind: str    # вид токена: IDENT, INT, KW_IF, SEMI, ... или EOF
    text: str    # кусок исходного текста (лексема)
    line: int    # строка, считая с 1
    col: int     # столбец, считая с 1 (в символах, а не в байтах)

    @property
    def pos(self):
        return (self.line, self.col)


@dataclass
class Diagnostic:
    """Сообщение об ошибке с позицией. Общее для лексера и парсера."""
    line: int
    col: int
    message: str

    def __str__(self):
        return f"{self.line}:{self.col}: {self.message}"


# 1. ТАБЛИЦА ИЗ HW1

_table_cache = None


def load_table(path=TABLE_PATH):
    """Прочитать funny_dfa.json один раз и запомнить."""
    global _table_cache
    if _table_cache is None:
        if not os.path.exists(path):
            raise SystemExit(f"нет файла {path}: сначала запустите  python lexgen.py")
        with open(path, encoding="utf-8") as f:
            _table_cache = json.load(f)
    return _table_cache


# 2. ПОЗИЦИИ
# Текст обрабатываем как байты UTF-8 (таблица ДКА — по байтам).

def move(chunk, line, col):
    """Сдвинуть позицию (line, col) на кусок байтов chunk."""
    for byte in chunk:
        if byte == 0x0A:                  # '\n' — новая строка
            line, col = line + 1, 1
        elif byte & 0xC0 != 0x80:         # не байт-продолжение UTF-8
            col += 1
    return line, col


# 3. ЛЕКСЕР

def tokenize(text):
    """Разбить текст на токены.

    Возвращает (tokens, errors):
        tokens — список Token, последний всегда EOF;
        errors — список Diagnostic (лексические ошибки).
    Пробелы и комментарии выбрасываются.
    """
    table = load_table()
    nxt, accept = table["next"], table["accept"]
    start, trap = table["start"], table["trap"]
    names = [t["name"] for t in table["tokens"]]
    kinds = [t["kind"] for t in table["tokens"]]

    data = text.encode("utf-8")

    def longest_match(pos):
        """Самый длинный токен, начинающийся в pos. Ответ: (номер токена или -1, конец)."""
        state = start
        best_token, best_end = -1, pos
        for i in range(pos, len(data)):
            state = nxt[state][data[i]]
            if state == trap:
                break                                  # дальше токен не продолжится
            if accept[state] >= 0:                     # здесь кончается токен — запомнить
                best_token, best_end = accept[state], i + 1
        return best_token, best_end

    def next_char(pos):
        """Позиция следующего СИМВОЛА (пропускаем байты-продолжения UTF-8)."""
        pos += 1
        while pos < len(data) and data[pos] & 0xC0 == 0x80:
            pos += 1
        return pos

    tokens, errors = [], []
    pos, line, col = 0, 1, 1
    while pos < len(data):
        token, end = longest_match(pos)

        if token < 0:
            # Отсюда не начинается ни один токен. Собираем все такие символы подряд
            # в одно сообщение («привет» — одна ошибка, а не 12 байтов-ошибок).
            bad_end = pos
            while bad_end < len(data) and longest_match(bad_end)[0] < 0:
                bad_end = next_char(bad_end)
            bad = data[pos:bad_end].decode("utf-8", errors="replace")
            errors.append(Diagnostic(line, col, f"недопустимый символ: '{bad}'"))
            line, col = move(data[pos:bad_end], line, col)
            pos = bad_end
            continue

        piece = data[pos:end].decode("utf-8")
        name, kind = names[token], kinds[token]
        if kind == "token":
            tokens.append(Token(name, piece, line, col))
        elif kind == "error":
            # BAD_INT (01, 007): сообщаем об ошибке, но отдаём парсеру обычный INT,
            # чтобы из-за одной лишней цифры не сыпались синтаксические ошибки.
            errors.append(Diagnostic(line, col, f"число с ведущим нулём: '{piece}'"))
            tokens.append(Token("INT", piece, line, col))
        # kind == "skip" (пробелы, комментарии) — просто пропускаем

        line, col = move(data[pos:end], line, col)
        pos = end

    tokens.append(Token("EOF", "", line, col))
    return tokens, errors
