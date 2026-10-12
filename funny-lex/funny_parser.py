"""
funny_parser.py — синтаксический анализатор Funny (HW2, ветка LL(1): рекурсивный спуск).

Идея рекурсивного спуска: на каждый нетерминал грамматики — своя функция parse_xxx().
Функция смотрит на ОДИН текущий токен (отсюда «LL(1)») и по нему решает, какое
правило применить. Грамматика целиком — в grammar.txt, тут у каждой функции в
docstring написано её правило.

Ошибки (режим паники):
    - в месте ошибки бросается исключение ParseError;
    - ловится оно в двух местах: в цикле операторов блока и в цикле определений модуля;
    - там ошибка записывается в список, а парсер пропускает токены до «надёжного»
      места (синхронизирующего токена) и продолжает разбор.
Так за один запуск находятся несколько ошибок, и парсер никогда не зацикливается:
каждая итерация цикла либо разбирает что-то, либо съедает хотя бы один токен.

Использование:
    module, errors = parse(text)      # module — AST (funny_ast.Module), errors — [Diagnostic]
"""
from funny_lexer import tokenize, Diagnostic
from funny_ast import (Module, VarDef, Function, Formula, Assign, If, While, Block,
                       Assert, Assume, Num, Bool, Var, Unary, Binary, Call, Index,
                       ArrayUpdate, Quantifier)


class ParseError(Exception):
    """Синтаксическая ошибка: где (line, col) и что (message)."""

    def __init__(self, line, col, message):
        super().__init__(message)
        self.line, self.col, self.message = line, col, message


# 1. КАК ПОКАЗЫВАТЬ ТОКЕНЫ В СООБЩЕНИЯХ

SYMBOLS = {
    "SEMI": ";", "COMMA": ",", "COLON": ":", "ASSIGN": "=",
    "LPAREN": "(", "RPAREN": ")", "LBRACKET": "[", "RBRACKET": "]",
    "LBRACE": "{", "RBRACE": "}", "ARROW": "->", "DARROW": "=>", "PIPE": "|",
}


def show_kind(kind):
    """Вид токена -> как его назвать в сообщении: SEMI -> ';', KW_IF -> 'if'."""
    if kind in SYMBOLS:
        return f"'{SYMBOLS[kind]}'"
    if kind.startswith("KW_"):
        return f"'{kind[3:].lower()}'"
    return {"IDENT": "имя", "INT": "число", "EOF": "конец файла"}.get(kind, kind)


# Операторы: вид токена -> строка оператора в AST
COMPARE_OPS = {"EQ": "==", "NE": "!=", "LT": "<", "LE": "<=", "GT": ">", "GE": ">="}
ADD_OPS = {"PLUS": "+", "MINUS": "-"}
MUL_OPS = {"STAR": "*", "SLASH": "/"}

# Синхронизирующие токены для оператора (режим паники в блоке).
# ';' — конец оператора (его съедаем); '{' '}' и ключевые слова — начало/конец
# следующей конструкции (их не трогаем, с них продолжим разбор).
STATEMENT_SYNC = ("SEMI", "LBRACE", "RBRACE", "KW_IF", "KW_WHILE", "KW_ASSERT", "KW_ASSUME", "EOF")


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens          # последний токен — всегда EOF
        self.pos = 0                  # номер текущего токена
        self.errors = []              # найденные синтаксические ошибки (Diagnostic)

    # 2. РАБОТА С ПОТОКОМ ТОКЕНОВ

    def peek(self):
        """Текущий токен (ровно один токен просмотра вперёд — LL(1))."""
        return self.tokens[self.pos]

    def at(self, *kinds):
        """Текущий токен одного из видов kinds?"""
        return self.peek().kind in kinds

    def advance(self):
        """Съесть текущий токен и вернуть его. На EOF стоим на месте."""
        token = self.peek()
        if token.kind != "EOF":
            self.pos += 1
        return token

    def expect(self, kind, message=None):
        """Съесть токен вида kind, а если там другой — синтаксическая ошибка."""
        if self.at(kind):
            return self.advance()
        prev = self.tokens[self.pos - 1] if self.pos > 0 else None
        if kind == "SEMI" and prev and self.peek().line > prev.line:
            # Забытая ';' в конце строки: показываем место сразу ПОСЛЕ предыдущего
            # токена, а не первый токен следующей строки — так понятнее.
            raise ParseError(prev.line, prev.col + len(prev.text), f"ожидалось ';' после '{prev.text}'")
        raise self.error(message or f"ожидалось {show_kind(kind)}")

    def error(self, message):
        """Создать ParseError в позиции текущего токена (бросает вызывающий: raise self.error(...))."""
        token = self.peek()
        if token.kind == "EOF":
            return ParseError(token.line, token.col, f"{message}, а файл закончился")
        return ParseError(token.line, token.col, f"{message}, а встретилось '{token.text}'")

    def report(self, err):
        """Записать ошибку. Вторую ошибку на том же месте не пишем — это обычно каскад."""
        if self.errors and (self.errors[-1].line, self.errors[-1].col) == (err.line, err.col):
            return
        self.errors.append(Diagnostic(err.line, err.col, err.message))

    def comma_list(self, parse_item):
        """item { "," item } — список через запятую, хотя бы один элемент."""
        items = [parse_item()]
        while self.at("COMMA"):
            self.advance()
            items.append(parse_item())
        return items

    # 3. МОДУЛЬ, ФУНКЦИИ, ФОРМУЛЫ

    def parse_module(self):
        """module = { definition } EOF"""
        items = []
        while not self.at("EOF"):
            start = self.pos
            try:
                items.append(self.parse_definition())
            except ParseError as err:
                self.report(err)
                self.recover_definition(start)
        if not items and not self.errors:
            eof = self.peek()
            self.report(ParseError(eof.line, eof.col, "пустая программа: нет ни одной функции или формулы"))
        return Module(items)

    def parse_definition(self):
        """
        definition = [ "function" ] IDENT "(" [ params ] ")" ( formulaRest | functionRest )

        Функция и формула начинаются одинаково: имя ( параметры ).
        Чтобы хватило одного токена просмотра, общее начало разбираем ОДИН раз
        (левая факторизация), а выбираем ветку по токену после ')':  '=>' — формула.
        """
        start = self.peek()
        has_keyword = self.at("KW_FUNCTION")      # "function" — необязательно (см. grammar.txt)
        if has_keyword:
            self.advance()
        name = self.expect("IDENT", "ожидалось имя функции или формулы")
        self.expect("LPAREN", f"ожидалась '(' после имени '{name.text}'")
        params = []
        if not self.at("RPAREN"):
            params = self.comma_list(self.parse_var_def)
        self.expect("RPAREN", "ожидалась ',' или ')' в списке параметров")

        if self.at("DARROW") and not has_keyword:
            return self.parse_formula_rest(name, params)
        return self.parse_function_rest(start, name, params)

    def parse_formula_rest(self, name, params):
        """formulaRest = "=>" predicate [ ";" ]"""
        self.advance()                             # '=>'
        body = self.parse_expr()
        if self.at("SEMI"):                        # ';' после формулы необязательна
            self.advance()
        return Formula(name.text, params, body, pos=name.pos)

    def parse_function_rest(self, start, name, params):
        """
        functionRest = [ "requires" predicate ]
                       "returns" varDef { "," varDef }
                       [ "ensures" predicate ]
                       [ "uses" localDef { "," localDef } ]
                       statement
        """
        requires = ensures = None
        uses = []
        if self.at("KW_REQUIRES"):
            self.advance()
            requires = self.parse_expr()
        self.expect("KW_RETURNS")
        returns = self.comma_list(self.parse_var_def)
        if self.at("KW_ENSURES"):
            self.advance()
            ensures = self.parse_expr()
        if self.at("KW_USES"):
            self.advance()
            uses = self.comma_list(self.parse_local_def)
        body = self.parse_statement()
        return Function(name.text, params, requires, returns, ensures, uses, body, pos=start.pos)

    def parse_var_def(self):
        """varDef = IDENT ":" type        — тип обязателен (параметры, возвраты, кванторы)"""
        name = self.expect("IDENT", "ожидалось имя переменной")
        self.expect("COLON", f"ожидалось ':' и тип после '{name.text}'")
        return VarDef(name.text, self.parse_type(), pos=name.pos)

    def parse_local_def(self):
        """localDef = IDENT [ ":" type ]  — для uses тип можно не писать"""
        name = self.expect("IDENT", "ожидалось имя переменной")
        var_type = None
        if self.at("COLON"):
            self.advance()
            var_type = self.parse_type()
        return VarDef(name.text, var_type, pos=name.pos)

    def parse_type(self):
        """type = "int" [ "[" "]" ]"""
        self.expect("KW_INT", "ожидался тип 'int' или 'int[]'")
        if self.at("LBRACKET"):
            self.advance()
            self.expect("RBRACKET", "ожидалась ']' в типе 'int[]'")
            return "int[]"
        return "int"

    def recover_definition(self, start):
        """Режим паники на верхнем уровне (ошибка в заголовке функции/формулы)."""
        if self.pos == start:
            # Ошибка на первом же токене: это вообще не начало определения (лишний токен).
            # Пропускаем до токена, с которого определение может начаться.
            self.advance()
            while not self.at("IDENT", "KW_FUNCTION", "EOF"):
                self.advance()
            return
        # Ошибка внутри заголовка. В заголовке нет ни '{', ни ';', поэтому первая
        # из них — начало тела функции или конец формулы.
        while not self.at("LBRACE", "SEMI", "KW_FUNCTION", "EOF"):
            self.advance()
        if self.at("SEMI"):
            self.advance()
        elif self.at("LBRACE"):
            # Тело всё равно разбираем: найдём ошибки и в нём (результат выбрасываем).
            try:
                self.parse_block()
            except ParseError as err:
                self.report(err)

    # 4. ОПЕРАТОРЫ

    def parse_statement(self):
        """statement = assignment | if | while | block | assert | assume
        Выбор — по первому токену (FIRST-множества не пересекаются)."""
        if self.at("IDENT"):
            return self.parse_assignment()
        if self.at("KW_IF"):
            return self.parse_if()
        if self.at("KW_WHILE"):
            return self.parse_while()
        if self.at("LBRACE"):
            return self.parse_block()
        if self.at("KW_ASSERT", "KW_ASSUME"):
            return self.parse_assert_assume()
        raise self.error("ожидался оператор")

    def parse_block(self):
        """block = "{" { statement } "}"   — здесь же восстановление после ошибок в операторах"""
        lbrace = self.expect("LBRACE")
        stmts = []
        while not self.at("RBRACE", "EOF"):
            start = self.pos
            try:
                stmts.append(self.parse_statement())
            except ParseError as err:
                self.report(err)
                self.recover_statement(start)
        self.expect("RBRACE", f"не закрыт блок, открытый в {lbrace.line}:{lbrace.col}: ожидалась '}}'")
        return Block(stmts, pos=lbrace.pos)

    def recover_statement(self, start):
        """Режим паники внутри блока: пропускаем токены до синхронизирующего."""
        while not self.at(*STATEMENT_SYNC):
            self.advance()
        if self.at("SEMI"):
            self.advance()                         # ';' закрывает сломанный оператор
        if self.pos == start:
            self.advance()                         # страховка: хоть один токен, но съесть

    def parse_assignment(self):
        """
        assignment = IDENT "=" expr ";"                    x = e;
                   | IDENT "[" expr "]" "=" expr ";"       a[i] = e;   (сахар)
                   | IDENT { "," IDENT } "=" call ";"      x, y = f(...);

        Все три варианта начинаются с IDENT — факторизуем: съедаем IDENT,
        а дальше выбираем по следующему токену: '[' / ',' / '='.
        """
        name = self.advance()

        if self.at("LPAREN"):
            # f(x);  — в Funny вызов не бывает отдельным оператором: результат надо присвоить
            bad = self.peek()
            raise ParseError(bad.line, bad.col,
                             f"вызов '{name.text}(...)' не может быть отдельным оператором — нужно x = {name.text}(...);")

        if self.at("LBRACKET"):
            # a[i] = v;  обессахариваем сразу:  a = ArrayUpdate(a, i, v)
            # (в funny.ru.md это записано как  a = set(a, i, v)).
            self.advance()
            index = self.parse_expr()
            self.expect("RBRACKET")
            self.expect("ASSIGN", "ожидалось '=' (обновление элемента массива: a[i] = v;)")
            value = self.parse_expr()
            self.expect("SEMI")
            update = ArrayUpdate(name.text, index, value, pos=name.pos)
            return Assign([name.text], update, pos=name.pos)

        targets = [name.text]
        while self.at("COMMA"):
            self.advance()
            targets.append(self.expect("IDENT", "ожидалось имя переменной").text)
        self.expect("ASSIGN", "ожидалось '='")

        if len(targets) > 1:
            # x, y = ...  справа может стоять только вызов функции
            callee = self.expect("IDENT", f"справа от '{', '.join(targets)} =' должен быть вызов функции")
            value = self.parse_call_rest(callee)
        else:
            value = self.parse_expr()
        self.expect("SEMI")
        return Assign(targets, value, pos=name.pos)

    def parse_if(self):
        """if = "if" "(" condition ")" statement [ "else" statement ]

        Висячий else: if (a) if (b) x=1; else x=2;  — else достаётся БЛИЖАЙШЕМУ if,
        потому что внутренний parse_if первым видит 'else' и забирает его.
        """
        keyword = self.advance()
        self.expect("LPAREN", "ожидалась '(' после 'if'")
        cond = self.parse_expr()
        self.expect("RPAREN", "ожидалась ')' после условия")
        then_branch = self.parse_statement()
        else_branch = None
        if self.at("KW_ELSE"):
            self.advance()
            else_branch = self.parse_statement()
        return If(cond, then_branch, else_branch, pos=keyword.pos)

    def parse_while(self):
        """while = "while" "(" condition ")" [ "invariant" predicate ] statement"""
        keyword = self.advance()
        self.expect("LPAREN", "ожидалась '(' после 'while'")
        cond = self.parse_expr()
        self.expect("RPAREN", "ожидалась ')' после условия")
        invariant = None
        if self.at("KW_INVARIANT"):
            self.advance()
            invariant = self.parse_expr()
        body = self.parse_statement()
        return While(cond, invariant, body, pos=keyword.pos)

    def parse_assert_assume(self):
        """assertStmt = "assert" predicate ";"     assumeStmt = "assume" predicate ";" """
        keyword = self.advance()
        pred = self.parse_expr()
        self.expect("SEMI")
        node = Assert if keyword.kind == "KW_ASSERT" else Assume
        return node(pred, pos=keyword.pos)

    # 5. ВЫРАЖЕНИЯ
    # Одна функция на уровень приоритета, от слабого к сильному:
    #     ->  <  or  <  and  <  not  <  сравнения  <  + -  <  * /  <  унарный -  <  primary
    # Левая рекурсия  E -> E + T  заменена циклом  E -> T { + T }  — это и есть
    # устранение левой рекурсии (E -> T E',  E' -> + T E' | ε), только записанное как while.

    def parse_expr(self):
        """expr = implies     (и арифметика, и условия, и предикаты — см. grammar.txt)"""
        return self.parse_implies()

    def parse_implies(self):
        """implies = or [ "->" implies ]   — правая ассоциативность: a -> b -> c = a -> (b -> c)"""
        left = self.parse_or()
        if self.at("ARROW"):
            op = self.advance()
            right = self.parse_implies()           # рекурсия ВПРАВО даёт правую ассоциативность
            return Binary("->", left, right, pos=op.pos)
        return left

    def parse_or(self):
        """or = and { "or" and }"""
        left = self.parse_and()
        while self.at("KW_OR"):
            op = self.advance()
            left = Binary("or", left, self.parse_and(), pos=op.pos)
        return left

    def parse_and(self):
        """and = not { "and" not }"""
        left = self.parse_not()
        while self.at("KW_AND"):
            op = self.advance()
            left = Binary("and", left, self.parse_not(), pos=op.pos)
        return left

    def parse_not(self):
        """not = "not" not | compare"""
        if self.at("KW_NOT"):
            op = self.advance()
            return Unary("not", self.parse_not(), pos=op.pos)
        return self.parse_compare()

    def parse_compare(self):
        """compare = sum [ relop sum ]    relop = == | != | < | <= | > | >=
        Сравнение не ассоциативно: a < b < c — ошибка."""
        left = self.parse_sum()
        if self.peek().kind in COMPARE_OPS:
            op = self.advance()
            left = Binary(COMPARE_OPS[op.kind], left, self.parse_sum(), pos=op.pos)
            if self.peek().kind in COMPARE_OPS:
                extra = self.peek()
                raise ParseError(extra.line, extra.col,
                                 "сравнения нельзя писать цепочкой (a < b < c) — используйте and")
        return left

    def parse_sum(self):
        """sum = term { ("+" | "-") term }    — левая ассоциативность: a - b - c = (a - b) - c"""
        left = self.parse_term()
        while self.peek().kind in ADD_OPS:
            op = self.advance()
            left = Binary(ADD_OPS[op.kind], left, self.parse_term(), pos=op.pos)
        return left

    def parse_term(self):
        """term = unary { ("*" | "/") unary }"""
        left = self.parse_unary()
        while self.peek().kind in MUL_OPS:
            op = self.advance()
            left = Binary(MUL_OPS[op.kind], left, self.parse_unary(), pos=op.pos)
        return left

    def parse_unary(self):
        """unary = "-" unary | primary"""
        if self.at("MINUS"):
            op = self.advance()
            return Unary("-", self.parse_unary(), pos=op.pos)
        return self.parse_primary()

    def parse_primary(self):
        """
        primary = INT | "true" | "false"
                | IDENT                         переменная
                | IDENT "(" [ args ] ")"        вызов функции / ссылка на формулу
                | IDENT "[" expr "]"            элемент массива
                | "length" "(" [ args ] ")"     встроенная функция
                | "(" expr ")"
                | quantifier
        """
        token = self.peek()
        if self.at("INT"):
            self.advance()
            return Num(int(token.text), pos=token.pos)
        if self.at("KW_TRUE", "KW_FALSE"):
            self.advance()
            return Bool(token.kind == "KW_TRUE", pos=token.pos)
        if self.at("LPAREN"):
            self.advance()
            inner = self.parse_expr()
            self.expect("RPAREN", "ожидалась ')'")
            return inner                           # скобки в AST не нужны: их задаёт структура дерева
        if self.at("KW_LENGTH"):
            self.advance()
            return self.parse_call_rest(token, name="length")
        if self.at("KW_FORALL", "KW_EXISTS"):
            return self.parse_quantifier()
        if self.at("IDENT"):
            self.advance()
            if self.at("LPAREN"):
                return self.parse_call_rest(token)
            if self.at("LBRACKET"):
                self.advance()
                index = self.parse_expr()
                self.expect("RBRACKET", "ожидалась ']'")
                return Index(token.text, index, pos=token.pos)
            return Var(token.text, pos=token.pos)
        raise self.error("ожидалось выражение")

    def parse_call_rest(self, name_token, name=None):
        """callRest = "(" [ expr { "," expr } ] ")"   — имя уже съедено"""
        self.expect("LPAREN", f"ожидалась '(' после '{name_token.text}'")
        args = []
        if not self.at("RPAREN"):
            args = self.comma_list(self.parse_expr)
        self.expect("RPAREN", "ожидалась ',' или ')' в списке аргументов")
        return Call(name or name_token.text, args, pos=name_token.pos)

    def parse_quantifier(self):
        """quantifier = ("forall" | "exists") "(" varDef "|" predicate ")" """
        keyword = self.advance()
        self.expect("LPAREN", f"ожидалась '(' после '{keyword.text}'")
        var = self.parse_var_def()
        self.expect("PIPE", "ожидалась '|' после переменной квантора")
        body = self.parse_expr()
        self.expect("RPAREN", "ожидалась ')' в конце квантора")
        return Quantifier(keyword.text, var, body, pos=keyword.pos)


# 6. ГЛАВНАЯ ФУНКЦИЯ

def parse(text):
    """Текст программы -> (AST, ошибки).

    AST строится всегда (даже с ошибками — из того, что удалось разобрать).
    Ошибки — лексические и синтаксические вместе, по порядку позиций.
    Если ошибок нет, AST полностью соответствует программе.
    """
    tokens, lex_errors = tokenize(text)
    parser = Parser(tokens)
    try:
        module = parser.parse_module()
    except RecursionError:                         # (((((...))))) глубже лимита Python
        module = Module([])
        parser.errors.append(Diagnostic(1, 1, "слишком глубокая вложенность выражений"))
    errors = sorted(lex_errors + parser.errors, key=lambda e: (e.line, e.col))
    return module, errors
