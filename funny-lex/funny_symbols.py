"""
funny_symbols.py — таблицы символов (HW3).

Таблица символов отвечает на вопрос «что значит это имя здесь?».

Области видимости в Funny (снаружи внутрь):
    модуль        имена функций и формул                  -> Signature, словарь в Checker
    функция       параметры -> возвращаемые значения -> локальные переменные
                  (три вложенные области: так requires видит только параметры,
                  ensures — параметры и возвраты, тело — всё)
    квантор       переменная forall/exists видна только внутри своего квантора

Блоки { } новых областей не создают: в Funny нет объявления переменной внутри блока,
локальная переменная объявляется в uses или первым присваиванием и видна до конца функции.

Имена функций (вызовы) и имена переменных — разные пространства имён:
f(x) ищется среди функций, x — среди переменных.
"""
from dataclasses import dataclass

# Как называть вид символа в сообщениях
KIND_RU = {
    "param": "параметр",
    "return": "возвращаемое значение",
    "local": "локальная переменная",
    "bound": "переменная квантора",
}


@dataclass
class Symbol:
    """Переменная: параметр, возвращаемое значение, локальная или переменная квантора."""
    name: str
    kind: str          # "param", "return", "local", "bound"
    type: object       # "int", "int[]" или TypeVar (тип локальной ещё не выведен)
    pos: tuple         # где объявлена (строка, столбец)


@dataclass
class Signature:
    """Функция или формула модуля: что принимает и что возвращает."""
    name: str
    kind: str          # "function" или "formula"
    params: list       # типы параметров: ["int", "int[]", ...]
    returns: list      # типы результатов функции; у формулы — ["bool"]
    pos: tuple


class Scope:
    """Одна область видимости: словарь имя -> Symbol и ссылка на внешнюю область."""

    def __init__(self, parent=None):
        self.parent = parent
        self.symbols = {}          # в порядке объявления (dict сохраняет порядок)

    def lookup(self, name):
        """Найти имя здесь или во внешних областях. Нет — None."""
        scope = self
        while scope is not None:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None

    def add(self, symbol):
        self.symbols[symbol.name] = symbol
