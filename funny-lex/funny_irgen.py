"""
funny_irgen.py — генерация трёхадресного кода из аннотированного AST (HW4).

Вход — модуль после HW3 (analyze/check без ошибок): у выражений есть type, у функций — locals.
Выход — IRModule (см. funny_ir.py). Формулы (formula ... => ...) в код не попадают:
они нужны только для верификации.

Как переводится каждая конструкция (шаблоны из лекции 6):

    x = e;                    код для e (результат в операнде o);  x := o
    x, y = f(a, b);           x, y := call f(a', b')
    a[i] = v;                 (после парсера это a = ArrayUpdate(a, i, v))  t := update(a, i', v'); a := t
    if (c) S1 else S2         cond(c, Lthen, Lelse)   Lthen: S1   goto Lend   Lelse: S2   Lend:
    while (c) S               Lhead: cond(c, Lbody, Lend)   Lbody: S   goto Lhead   Lend:
    assert/assume P;          в код не попадают (проверяются при верификации, см. funny.ru.md)
    конец функции             return r1, ..., rm  (значения возвращаемых переменных)

Выражения (expr) возвращают ОПЕРАНД: константу, имя переменной или новую временную.
Каждая операция кладёт результат в свою временную t1, t2, ... — «наивный» код,
лишние копии потом убирают оптимизации (funny_opt.py).

Условия (cond) переводятся «прыжками» (jumping code): вместо логического значения —
переходы на метку «истина» или «ложь». Так and/or/-> получают короткое замыкание,
как в Java: в  b != 0 and a / b > 1  деление не выполняется при b == 0.
Сравнение даёт временную типа bool и пару  if t goto Ltrue; goto Lfalse.
"""
from funny_ast import (Function, Assign, If, While, Block, Assert, Assume,
                       Num, Bool, Var, Unary, Binary, Call as CallExpr, Index, ArrayUpdate)
from funny_ir import (INT, ARRAY, BOOL, IRFunction, IRModule,
                      Label, Copy, BinOp, UnOp, Length, Load, Update, Goto, IfGoto, Call, Return)

ARITH = {"+", "-", "*", "/"}
COMPARE = {"==", "!=", "<", "<=", ">", ">="}


class FunctionGen:
    """Генератор кода одной функции."""

    def __init__(self, fn):
        self.fn = fn
        self.user_names = {v.name for v in fn.params + fn.returns + (fn.locals or [])}
        self.ir = IRFunction(
            name=fn.name,
            params=[(v.name, v.type) for v in fn.params],
            returns=[(v.name, v.type) for v in fn.returns],
            locals=[(v.name, v.type) for v in (fn.locals or [])],
        )
        self.temp_count = 0
        self.label_count = 0

    # --- вспомогательное ---

    def emit(self, instr):
        self.ir.code.append(instr)

    def new_temp(self, type_):
        """Новая временная t<N>. Имя не должно совпасть с переменной программы (в Funny можно назвать переменную t1)."""
        while True:
            self.temp_count += 1
            name = f"t{self.temp_count}"
            if name not in self.user_names:
                self.ir.temps[name] = type_
                return name

    def new_label(self):
        self.label_count += 1
        return f"L{self.label_count}"

    # --- функция ---

    def generate(self):
        self.statement(self.fn.body)
        self.emit(Return([v.name for v in self.fn.returns]))
        return self.ir

    # --- операторы ---

    def statement(self, s):
        if isinstance(s, Block):
            for st in s.stmts:
                self.statement(st)
        elif isinstance(s, Assign):
            self.assign(s)
        elif isinstance(s, If):
            then_label = self.new_label()
            if s.else_branch is None:
                end_label = self.new_label()
                self.cond(s.cond, then_label, end_label)
                self.emit(Label(then_label))
                self.statement(s.then_branch)
            else:
                else_label, end_label = self.new_label(), self.new_label()
                self.cond(s.cond, then_label, else_label)
                self.emit(Label(then_label))
                self.statement(s.then_branch)
                self.emit(Goto(end_label))
                self.emit(Label(else_label))
                self.statement(s.else_branch)
            self.emit(Label(end_label))
        elif isinstance(s, While):
            head, body, end = self.new_label(), self.new_label(), self.new_label()
            self.emit(Label(head))
            self.cond(s.cond, body, end)
            self.emit(Label(body))
            self.statement(s.body)
            self.emit(Goto(head))
            self.emit(Label(end))
        elif isinstance(s, (Assert, Assume)):
            pass                     # только для верификации; в исполняемый код не попадают
        else:
            raise ValueError(f"неизвестный оператор {type(s).__name__}")

    def assign(self, s):
        if len(s.targets) > 1:                     # x, y = f(...)
            call = s.value
            args = [self.expr(a) for a in call.args]
            self.emit(Call(list(s.targets), call.name, args))
        else:                                      # x = e  (в том числе a = ArrayUpdate(...))
            self.emit(Copy(s.targets[0], self.expr(s.value)))

    # --- выражения: результат — операнд ---

    def expr(self, e):
        if isinstance(e, Num):
            return e.value
        if isinstance(e, Var):
            return e.name
        if isinstance(e, Unary) and e.op == "-":
            arg = self.expr(e.operand)
            t = self.new_temp(INT)
            self.emit(UnOp(t, "-", arg))
            return t
        if isinstance(e, Binary) and e.op in ARITH:
            left = self.expr(e.left)               # аргументы слева направо — как в funny.ru.md
            right = self.expr(e.right)
            t = self.new_temp(INT)
            self.emit(BinOp(t, e.op, left, right))
            return t
        if isinstance(e, Index):
            index = self.expr(e.index)
            t = self.new_temp(INT)
            self.emit(Load(t, e.array, index))
            return t
        if isinstance(e, ArrayUpdate):
            index = self.expr(e.index)
            value = self.expr(e.value)
            t = self.new_temp(ARRAY)
            self.emit(Update(t, e.array, index, value))
            return t
        if isinstance(e, CallExpr) and e.name == "length":
            array = self.expr(e.args[0])
            t = self.new_temp(INT)
            self.emit(Length(t, array))
            return t
        if isinstance(e, CallExpr):
            args = [self.expr(a) for a in e.args]
            t = self.new_temp(e.type)              # тип результата записал HW3
            self.emit(Call([t], e.name, args))
            return t
        # Сравнения и логика встречаются только в условиях (в Funny нет bool-переменных),
        # формулы и кванторы — только в предикатах. HW3 это гарантирует.
        raise ValueError(f"выражение {type(e).__name__} нельзя вычислить как значение")

    # --- условия: переходы на метки ---

    def cond(self, e, true_label, false_label):
        if isinstance(e, Bool):
            self.emit(Goto(true_label if e.value else false_label))
        elif isinstance(e, Unary) and e.op == "not":
            self.cond(e.operand, false_label, true_label)
        elif isinstance(e, Binary) and e.op == "and":
            mid = self.new_label()
            self.cond(e.left, mid, false_label)    # левое ложно — всё ложно, правое не считаем
            self.emit(Label(mid))
            self.cond(e.right, true_label, false_label)
        elif isinstance(e, Binary) and e.op == "or":
            mid = self.new_label()
            self.cond(e.left, true_label, mid)     # левое истинно — всё истинно
            self.emit(Label(mid))
            self.cond(e.right, true_label, false_label)
        elif isinstance(e, Binary) and e.op == "->":
            mid = self.new_label()
            self.cond(e.left, mid, true_label)     # a -> b  ==  not a or b
            self.emit(Label(mid))
            self.cond(e.right, true_label, false_label)
        elif isinstance(e, Binary) and e.op in COMPARE:
            left = self.expr(e.left)
            right = self.expr(e.right)
            t = self.new_temp(BOOL)
            self.emit(BinOp(t, e.op, left, right))
            self.emit(IfGoto(t, true_label))
            self.emit(Goto(false_label))
        else:
            raise ValueError(f"условие {type(e).__name__} нельзя исполнить (формулы и кванторы — только для верификации)")


def generate(module):
    """Аннотированный AST (HW3, без ошибок) -> IRModule. Формулы пропускаются."""
    return IRModule([FunctionGen(item).generate() for item in module.items if isinstance(item, Function)])
