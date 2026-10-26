"""
funny_types.py — типы языка Funny и унификация (HW3).

Типы — обычные строки:
    "int"     целое число
    "int[]"   массив целых
    "bool"    логическое значение; бывает только у условий и предикатов
              (переменных типа bool в Funny нет)
Плюс два служебных вида:
    кортеж    tuple из типов, например ("int", "int") — результат функции
              с несколькими returns; его можно только разложить: x, y = f(...);
    TypeVar   «тип пока неизвестен» — у локальной переменной без аннотации
              до первого присваивания 

Унификация — «сделать два типа одинаковыми»: если один из них неизвестен (TypeVar),
он становится равен другому; если оба известны и разные — конфликт (ошибка типов).
"""

INT = "int"
ARRAY = "int[]"
BOOL = "bool"
ERROR = "error"     # тип выражения, в котором уже нашли ошибку: совместим со всем,
                    # чтобы одна ошибка не порождала цепочку новых сообщений


class TypeVar:
    """Переменная типа: неизвестный пока тип локальной переменной."""

    def __init__(self, name):
        self.name = name        # имя переменной программы — для сообщений
        self.ref = None         # во что превратилась; None — пока неизвестно

    def __repr__(self):
        return f"?{self.name}"


def resolve(t):
    """Пройти по цепочке TypeVar до настоящего типа (или до ещё не известной TypeVar)."""
    while isinstance(t, TypeVar) and t.ref is not None:
        t = t.ref
    return t


def unify(a, b):
    """Сделать типы a и b одинаковыми. True — получилось, False — конфликт типов."""
    a, b = resolve(a), resolve(b)
    if a is b or a == b:
        return True
    if a == ERROR or b == ERROR:          # с ошибочным типом молча соглашаемся
        for t in (a, b):
            if isinstance(t, TypeVar):
                t.ref = ERROR
        return True
    if isinstance(a, TypeVar):            # неизвестный тип становится известным
        a.ref = b
        return True
    if isinstance(b, TypeVar):
        b.ref = a
        return True
    return False                          # два разных известных типа


def show(t):
    """Тип -> строка для сообщений и аннотаций AST."""
    t = resolve(t)
    if isinstance(t, TypeVar):
        return "?"
    if isinstance(t, tuple):
        return "(" + ", ".join(show(x) for x in t) + ")"
    return t
