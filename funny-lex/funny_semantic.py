"""
funny_semantic.py — семантический анализ Funny: имена, типы, вывод типов локальных.

Вход — AST от парсера(funny_parser.py). Выход — список ошибок, а само дерево дополняется:
    - у каждого выражения заполняется поле type ("int", "int[]", "bool", "(int, int)");
    - у каждой функции заполняется поле locals — локальные переменные и их типы.

Как устроен проход:
    1. Сигнатуры. Сначала собираем заголовки всех функций и формул модуля.
       Поэтому можно вызвать функцию, объявленную ниже, и рекурсивную функцию.
    2. Тела. Обходим каждую функцию по порядку операторов: проверяем имена и типы,
       локальные переменные объявляются первым присваиванием (или в uses).
    3. Итог вывода типов. Если тип локальной так и не стал известен — ошибка.

Ошибки не останавливают проверку: о каждой пишем и идём дальше. Выражение с ошибкой
получает тип ERROR, который совместим со всем, — так одна ошибка не тянет за собой другие.

Использование:
    module, errors = parse(text)
    if not errors:
        errors = check(module)       # дерево аннотируется на месте
или сразу:
    module, errors = analyze(text)
"""
from funny_ast import (Function, VarDef, Assign, If, While, Block, Assert, Assume,
                       Num, Bool, Var, Unary, Binary, Call, Index, ArrayUpdate, Quantifier,
                       Expr, walk)
from funny_lexer import Diagnostic
from funny_parser import parse
from funny_symbols import Scope, Symbol, Signature, KIND_RU
from funny_types import INT, ARRAY, BOOL, ERROR, TypeVar, resolve, unify, show

ARITH_OPS = {"+", "-", "*", "/"}                  # int, int -> int
COMPARE_OPS = {"==", "!=", "<", "<=", ">", ">="}  # int, int -> bool
LOGIC_OPS = {"and", "or", "->"}                   # bool, bool -> bool


class Checker:
    def __init__(self):
        self.errors = []
        self.signatures = {}       # имя -> Signature: все функции и формулы модуля
        # про текущую функцию:
        self.where = ""            # где мы: "requires", "ensures", "тело" ... — для сообщений
        self.known_names = {}      # имя -> вид ("param"/"return"/"local") во всей функции
        self.reported = set()      # о каких неизвестных именах уже сообщили (не повторяем)

    def error(self, pos, message):
        diag = Diagnostic(pos[0], pos[1], message)
        if all((e.line, e.col, e.message) != (diag.line, diag.col, diag.message) for e in self.errors):
            self.errors.append(diag)

    def expect(self, node, actual, expected, what):
        """Проверить (унифицировать), что выражение node имеет тип expected. Иначе — ошибка."""
        if unify(actual, expected):
            return True
        if expected == BOOL:
            self.error(node.pos, f"{what}: ожидалось логическое условие (сравнение, and, or, not), "
                                 f"а здесь {show(actual)}")
        else:
            self.error(node.pos, f"{what}: ожидался тип {expected}, а здесь {show(actual)}")
        return False

    def declare(self, scope, symbol):
        """Объявить переменную. Если имя уже видно отсюда — повторное объявление."""
        old = scope.lookup(symbol.name)
        if old is not None:
            self.error(symbol.pos, f"повторное объявление '{symbol.name}': уже объявлено как "
                                   f"{KIND_RU[old.kind]} в {old.pos[0]}:{old.pos[1]}")
            return False
        scope.add(symbol)
        return True

    # 1. МОДУЛЬ

    def check_module(self, module):
        for item in module.items:                  # проход 1: сигнатуры
            self.declare_signature(item)
        for item in module.items:                  # проход 2: тела
            if isinstance(item, Function):
                self.check_function(item)
            else:
                self.check_formula(item)
        finalize_types(module)
        self.errors.sort(key=lambda e: (e.line, e.col))
        return self.errors

    def declare_signature(self, item):
        if item.name in self.signatures:
            old = self.signatures[item.name]
            what = "функция" if old.kind == "function" else "формула"
            self.error(item.pos, f"повторное объявление '{item.name}': уже есть {what} "
                                 f"с таким именем в {old.pos[0]}:{old.pos[1]}")
            return
        params = [p.type for p in item.params]
        if isinstance(item, Function):
            sig = Signature(item.name, "function", params, [r.type for r in item.returns], item.pos)
        else:
            sig = Signature(item.name, "formula", params, [BOOL], item.pos)
        self.signatures[item.name] = sig

    # 2. ФУНКЦИИ И ФОРМУЛЫ

    def check_function(self, fn):
        # Три вложенные области: параметры <- возвращаемые значения <- локальные
        params = Scope()
        for p in fn.params:
            self.declare(params, Symbol(p.name, "param", p.type, p.pos))
        returns = Scope(params)
        for r in fn.returns:
            self.declare(returns, Symbol(r.name, "return", r.type, r.pos))
        body = Scope(returns)
        for v in fn.uses:                          # uses x:int  или  uses x  (тип выведем)
            self.declare(body, Symbol(v.name, "local", v.type or TypeVar(v.name), v.pos))

        # Все имена функции заранее — только чтобы писать понятные сообщения
        # («используется до первого присваивания», «в requires нельзя возвращаемое значение»).
        self.known_names = {}
        for name in assigned_names(fn.body):
            self.known_names[name] = "local"
        for v in fn.uses:
            self.known_names[v.name] = "local"
        for r in fn.returns:
            self.known_names[r.name] = "return"
        for p in fn.params:
            self.known_names[p.name] = "param"
        self.reported = set()

        if fn.requires is not None:                # requires видит только параметры
            self.where = "requires"
            self.predicate(fn.requires, params, "requires")
        if fn.ensures is not None:                 # ensures — параметры и возвращаемые значения
            self.where = "ensures"
            self.predicate(fn.ensures, returns, "ensures")
        self.where = "тело"
        self.statement(fn.body, body)

        # Итог вывода типов локальных переменных
        fn.locals = []
        for sym in body.symbols.values():
            t = resolve(sym.type)
            if isinstance(t, TypeVar):
                self.error(sym.pos, f"не удалось вывести тип локальной переменной '{sym.name}': "
                                    f"ей не присваивается ни одно значение известного типа — укажите тип: uses {sym.name}:int")
            fn.locals.append(VarDef(sym.name, show(t), pos=sym.pos))

    def check_formula(self, formula):
        scope = Scope()
        for p in formula.params:
            self.declare(scope, Symbol(p.name, "param", p.type, p.pos))
        self.known_names = {p.name: "param" for p in formula.params}
        self.reported = set()
        self.where = "формула"
        self.predicate(formula.body, scope, f"тело формулы '{formula.name}'")

    # 3. ОПЕРАТОРЫ

    def statement(self, s, scope):
        if isinstance(s, Block):
            for inner in s.stmts:
                self.statement(inner, scope)
        elif isinstance(s, Assign):
            self.assign(s, scope)
        elif isinstance(s, If):
            cond = self.expr(s.cond, scope, spec=False)
            self.expect(s.cond, cond, BOOL, "условие if")
            self.statement(s.then_branch, scope)
            if s.else_branch is not None:
                self.statement(s.else_branch, scope)
        elif isinstance(s, While):
            cond = self.expr(s.cond, scope, spec=False)
            self.expect(s.cond, cond, BOOL, "условие while")
            if s.invariant is not None:
                self.predicate(s.invariant, scope, "invariant")
            self.statement(s.body, scope)
        elif isinstance(s, (Assert, Assume)):
            self.predicate(s.pred, scope, "assert" if isinstance(s, Assert) else "assume")

    def predicate(self, e, scope, what):
        """requires / ensures / invariant / assert / assume / тело формулы: логическое, spec=True."""
        t = self.expr(e, scope, spec=True)
        self.expect(e, t, BOOL, what)

    def assign(self, s, scope):
        if len(s.targets) > 1:
            self.assign_tuple(s, scope)
            return
        value = self.expr(s.value, scope, spec=False)
        self.assign_to(s.targets[0], value, s, scope)

    def assign_tuple(self, s, scope):
        """x, y = f(...);  — число и типы переменных слева = returns функции."""
        for i, name in enumerate(s.targets):
            if name in s.targets[:i]:
                self.error(s.pos, f"переменная '{name}' повторяется в левой части присваивания")
        call = s.value                             # парсер гарантирует, что справа вызов
        result = self.call(call, scope, spec=False)
        call.type = result
        result = resolve(result)
        if result == ERROR:
            values = [ERROR] * len(s.targets)
        else:
            values = list(result) if isinstance(result, tuple) else [result]
            if len(values) != len(s.targets):
                self.error(s.pos, f"'{call.name}' возвращает значений: {len(values)}, "
                                  f"а слева переменных: {len(s.targets)}")
                values = [ERROR] * len(s.targets)
        for name, value in zip(s.targets, values):
            self.assign_to(name, value, s, scope)

    def assign_to(self, name, value, s, scope):
        """Присвоить значение типа value переменной name."""
        if resolve(value) == BOOL:
            self.error(s.pos, f"нельзя присвоить логическое значение переменной '{name}': "
                              f"в Funny нет переменных типа bool")
            value = ERROR
        sym = scope.lookup(name)
        if sym is None:
            # Первое присваивание объявляет локальную переменную; её тип — тип значения
            sym = Symbol(name, "local", TypeVar(name), s.pos)
            scope.add(sym)
        elif sym.kind == "param":
            if isinstance(s.value, ArrayUpdate):
                self.error(s.pos, f"нельзя изменить параметр-массив '{name}': параметры только для чтения "
                                  f"({name}[i] = v создаёт новый массив и присваивает его '{name}'); "
                                  f"скопируйте его в локальную переменную: b = {name};")
            else:
                self.error(s.pos, f"нельзя присвоить параметру '{name}': параметры только для чтения")
            return
        if not unify(sym.type, value):
            self.error(s.pos, f"нельзя присвоить {show(value)} переменной '{name}' типа {show(sym.type)}")

    # 4. ВЫРАЖЕНИЯ
    # spec=True — мы внутри предиката (requires, ensures, invariant, assert, assume, формула):
    # только там разрешены кванторы и ссылки на формулы.

    def expr(self, e, scope, spec):
        """Проверить выражение, записать его тип в e.type и вернуть тип."""
        t = self._expr(e, scope, spec)
        e.type = t
        r = resolve(t)
        if isinstance(r, tuple):
            # Функция с несколькими returns внутри выражения — нельзя (только x, y = f(...);)
            self.error(e.pos, f"функция '{e.name}' возвращает несколько значений {show(r)}: "
                              f"её можно вызвать только присваиванием вида "
                              f"{', '.join('v' + str(i + 1) for i in range(len(r)))} = {e.name}(...);")
            return ERROR
        return t

    def _expr(self, e, scope, spec):
        if isinstance(e, Num):
            return INT
        if isinstance(e, Bool):
            return BOOL
        if isinstance(e, Var):
            return self.variable(e.name, e.pos, scope)
        if isinstance(e, Unary):
            t = self.expr(e.operand, scope, spec)
            if e.op == "-":
                self.expect(e.operand, t, INT, "унарный минус")
                return INT
            self.expect(e.operand, t, BOOL, "not")
            return BOOL
        if isinstance(e, Binary):
            left = self.expr(e.left, scope, spec)
            right = self.expr(e.right, scope, spec)
            if e.op in LOGIC_OPS:
                self.expect(e.left, left, BOOL, f"левый операнд '{e.op}'")
                self.expect(e.right, right, BOOL, f"правый операнд '{e.op}'")
                return BOOL
            self.expect(e.left, left, INT, f"левый операнд '{e.op}'")
            self.expect(e.right, right, INT, f"правый операнд '{e.op}'")
            return BOOL if e.op in COMPARE_OPS else INT
        if isinstance(e, Index):                   # a[i]
            array = self.variable(e.array, e.pos, scope)
            self.expect(e, array, ARRAY, f"'{e.array}' в {e.array}[...]")
            index = self.expr(e.index, scope, spec)
            self.expect(e.index, index, INT, "индекс массива")
            return INT
        if isinstance(e, ArrayUpdate):             # a[i] = v  ->  a = ArrayUpdate(a, i, v)
            array = self.variable(e.array, e.pos, scope)
            self.expect(e, array, ARRAY, f"'{e.array}' в {e.array}[...] = ...")
            index = self.expr(e.index, scope, spec)
            self.expect(e.index, index, INT, "индекс массива")
            value = self.expr(e.value, scope, spec)
            self.expect(e.value, value, INT, "элемент массива")
            return ARRAY
        if isinstance(e, Call):
            return self.call(e, scope, spec)
        if isinstance(e, Quantifier):
            return self.quantifier(e, scope, spec)
        raise TypeError(f"неизвестный узел {type(e).__name__}")

    def variable(self, name, pos, scope):
        """Тип переменной по таблице символов. Нет такой — понятная ошибка."""
        sym = scope.lookup(name)
        if sym is not None:
            return sym.type
        if name not in self.reported:
            self.reported.add(name)
            self.error(pos, self.unknown_name_message(name))
        return ERROR

    def unknown_name_message(self, name):
        kind = self.known_names.get(name)
        if self.where == "requires" and kind in ("return", "local"):
            return f"в requires можно использовать только параметры, а '{name}' — {KIND_RU[kind]}"
        if self.where == "ensures" and kind == "local":
            return (f"в ensures можно использовать только параметры и возвращаемые значения, "
                    f"а '{name}' — локальная переменная")
        if kind == "local":
            return f"переменная '{name}' используется до первого присваивания"
        if name in self.signatures:
            what = "функция" if self.signatures[name].kind == "function" else "формула"
            return f"'{name}' — {what}, а не переменная"
        return f"неизвестное имя '{name}'"

    def call(self, e, scope, spec):
        """Вызов функции, length(...) или ссылка на формулу. Возвращает тип результата
        (у функции с несколькими returns — кортеж)."""
        args = [self.expr(a, scope, spec) for a in e.args]

        if e.name == "length":                     # встроенная length(a: int[]) returns int
            if len(args) != 1:
                self.error(e.pos, f"неверное число аргументов 'length': ожидается 1, передано {len(args)}")
            else:
                self.expect(e.args[0], args[0], ARRAY, "аргумент length")
            return INT

        sig = self.signatures.get(e.name)
        if sig is None:
            if scope.lookup(e.name) is not None:
                self.error(e.pos, f"'{e.name}' — переменная, а не функция")
            else:
                self.error(e.pos, f"неизвестная функция '{e.name}'")
            return ERROR
        if sig.kind == "formula" and not spec:
            self.error(e.pos, f"формулу '{e.name}' можно использовать только в предикатах "
                              f"(requires, ensures, invariant, assert, assume)")
        if len(args) != len(sig.params):
            self.error(e.pos, f"неверное число аргументов '{e.name}': ожидается {len(sig.params)}, "
                              f"передано {len(args)}")
        else:
            for i, (arg, actual, expected) in enumerate(zip(e.args, args, sig.params), 1):
                self.expect(arg, actual, expected, f"аргумент {i} '{e.name}'")
        if sig.kind == "formula":
            return BOOL
        if len(sig.returns) == 1:
            return sig.returns[0]
        return tuple(sig.returns)

    def quantifier(self, e, scope, spec):
        """forall (k:int | P) / exists (k:int | P): переменная видна только внутри."""
        if not spec:
            self.error(e.pos, f"квантор {e.kind} можно использовать только в предикатах "
                              f"(requires, ensures, invariant, assert, assume)")
        inner = Scope(scope)
        self.declare(inner, Symbol(e.var.name, "bound", e.var.type, e.var.pos))
        body = self.expr(e.body, inner, spec=True)
        self.expect(e.body, body, BOOL, f"тело {e.kind}")
        return BOOL


# 5. ВСПОМОГАТЕЛЬНОЕ

def assigned_names(s):
    """Имена всех переменных, которым что-то присваивается в операторе s (в любом месте)."""
    if isinstance(s, Assign):
        return list(s.targets)
    if isinstance(s, Block):
        return [n for inner in s.stmts for n in assigned_names(inner)]
    if isinstance(s, If):
        names = assigned_names(s.then_branch)
        if s.else_branch is not None:
            names += assigned_names(s.else_branch)
        return names
    if isinstance(s, While):
        return assigned_names(s.body)
    return []


def finalize_types(module):
    """После проверки: заменить в аннотациях TypeVar на итоговые типы-строки."""
    for node in walk(module):
        if isinstance(node, Expr) and node.type is not None:
            node.type = show(node.type)


def check(module):
    """Семантический анализ готового AST. Дерево аннотируется на месте. Возвращает список ошибок."""
    return Checker().check_module(module)


def analyze(text):
    """Текст -> (AST, ошибки): парсер, а если синтаксис в порядке — семантический анализ."""
    module, errors = parse(text)
    if errors:
        return module, errors
    return module, check(module)
