"""
funny_cfg.py — базовые блоки, управляющий граф (CFG) и анализ живых переменных (HW4).

Базовый блок — участок кода, который выполняется целиком: войти можно только в начало,
выйти — только из конца. Первые команды блоков («лидеры»):
    1) первая команда функции;
    2) метка (на неё может быть переход);
    3) команда сразу после goto / if-goto / return.
Исключение, как в лекции 6: пара  if t goto L1 ; goto L2  — одно ветвление на два направления,
поэтому goto после if-goto остаётся в том же блоке и закрывает его.

Рёбра CFG (по последней команде блока):
    goto L                    -> блок с меткой L
    if t goto L1 ; goto L2    -> L1 (true), L2 (false)
    if t goto L1              -> L1 (true), следующий блок (false)
    return                    -> рёбер нет: это выходной блок
    другое                    -> следующий блок (проход насквозь)

Анализ живых переменных (лекция 6, «Анализ активных переменных»):
    use(B) — переменные, которые B читает до того, как сам их запишет;
    def(B) — переменные, которые B записывает;
    out(B) = объединение in(S) по всем преемникам S;
    in(B)  = use(B) ∪ (out(B) \\ def(B));
    повторяем, пока множества меняются.
"""
from dataclasses import dataclass, field

from funny_ir import Label, Goto, IfGoto, Return, JUMPS


@dataclass
class BasicBlock:
    name: str                                  # B1, B2, ...
    instrs: list                               # инструкции блока (метка, если есть, — первая)
    succs: list = field(default_factory=list)  # [(имя блока, подпись ребра)]
    preds: list = field(default_factory=list)  # [имя блока]
    live_in: set = field(default_factory=set)
    live_out: set = field(default_factory=set)

    @property
    def label(self):
        return self.instrs[0].name if self.instrs and isinstance(self.instrs[0], Label) else None


@dataclass
class CFG:
    function: object
    blocks: list                               # [BasicBlock] в порядке кода; первый — входной

    def block(self, name):
        for b in self.blocks:
            if b.name == name:
                return b
        raise KeyError(name)

    @property
    def entry(self):
        return self.blocks[0]

    def exits(self):
        return [b for b in self.blocks if b.instrs and isinstance(b.instrs[-1], Return)]

    def code(self):
        """Обратно в линейный код: блоки подряд."""
        return [ins for b in self.blocks for ins in b.instrs]


def split_blocks(code):
    """Список инструкций -> список списков (блоков) по правилу лидеров."""
    blocks, current = [], []
    for i, ins in enumerate(code):
        if isinstance(ins, Label) and current:             # лидер: метка
            blocks.append(current)
            current = []
        current.append(ins)
        if isinstance(ins, JUMPS):                          # лидер: команда после перехода
            pair = isinstance(ins, IfGoto) and i + 1 < len(code) and isinstance(code[i + 1], Goto)
            if not pair:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)
    return blocks


def build_cfg(fn):
    """IRFunction -> CFG с рёбрами (без живости; её считает liveness)."""
    blocks = [BasicBlock(f"B{i + 1}", instrs) for i, instrs in enumerate(split_blocks(fn.code))]
    by_label = {b.label: b for b in blocks if b.label}
    for i, b in enumerate(blocks):
        nxt = blocks[i + 1].name if i + 1 < len(blocks) else None
        last = b.instrs[-1]
        before = b.instrs[-2] if len(b.instrs) >= 2 else None
        if isinstance(last, Return):
            continue
        if isinstance(last, Goto) and isinstance(before, IfGoto):
            b.succs = [(by_label[before.label].name, "true"), (by_label[last.label].name, "false")]
        elif isinstance(last, Goto):
            b.succs = [(by_label[last.label].name, "")]
        elif isinstance(last, IfGoto):
            b.succs = [(by_label[last.label].name, "true")] + ([(nxt, "false")] if nxt else [])
        elif nxt:
            b.succs = [(nxt, "")]
    for b in blocks:
        for s, _ in b.succs:
            cfg_block = next(x for x in blocks if x.name == s)
            if b.name not in cfg_block.preds:
                cfg_block.preds.append(b.name)
    return CFG(fn, blocks)


def use_def(instrs):
    """use(B) и def(B) для списка инструкций блока."""
    use, defined = set(), set()
    for ins in instrs:
        for v in ins.uses():
            if v not in defined:
                use.add(v)
        defined.update(ins.defs())
    return use, defined


def liveness(cfg):
    """Заполнить live_in/live_out всех блоков (итерации до неподвижной точки). Возвращает число итераций."""
    info = {b.name: use_def(b.instrs) for b in cfg.blocks}
    for b in cfg.blocks:
        b.live_in, b.live_out = set(), set()
    rounds = 0
    changed = True
    while changed:
        changed = False
        rounds += 1
        for b in reversed(cfg.blocks):                     # обратный порядок — быстрее сходится
            out = set()
            for s, _ in b.succs:
                out |= cfg.block(s).live_in
            use, defined = info[b.name]
            new_in = use | (out - defined)
            if new_in != b.live_in or out != b.live_out:
                b.live_in, b.live_out = new_in, out
                changed = True
    return rounds


def live_after_each(block):
    """Живые переменные ПОСЛЕ каждой инструкции блока (нужно для DCE и графа конфликтов).
    Идём от конца блока к началу: live = (live \\ def) ∪ use."""
    live = set(block.live_out)
    result = [None] * len(block.instrs)
    for i in range(len(block.instrs) - 1, -1, -1):
        result[i] = set(live)
        ins = block.instrs[i]
        live -= set(ins.defs())
        live |= set(ins.uses())
    return result


def reachable(cfg):
    """Имена блоков, достижимых из входного."""
    seen, stack = set(), [cfg.entry.name]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack.extend(s for s, _ in cfg.block(name).succs)
    return seen


# ---------- вывод ----------

def format_cfg(cfg, with_liveness=True):
    lines = [f"CFG {cfg.function.name}: вход {cfg.entry.name}, выход {', '.join(b.name for b in cfg.exits()) or '—'}"]
    for b in cfg.blocks:
        succ = ", ".join(f"{s}" + (f" ({k})" if k else "") for s, k in b.succs) or "—"
        lines.append(f"  {b.name}  pred: {', '.join(b.preds) or '—'}   succ: {succ}")
        if with_liveness:
            lines.append(f"      in:  {{{', '.join(sorted(b.live_in))}}}")
            lines.append(f"      out: {{{', '.join(sorted(b.live_out))}}}")
        for ins in b.instrs:
            lines.append(("    " if isinstance(ins, Label) else "      ") + str(ins))
    return "\n".join(lines)


def _dot_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\<").replace(">", "\\>") \
            .replace("{", "\\{").replace("}", "\\}").replace("|", "\\|")


def cfg_to_dot(cfg, title=None):
    """CFG в формате Graphviz DOT: блок — прямоугольник с кодом, рёбра подписаны true/false."""
    name = title or cfg.function.name
    lines = [f'digraph "{name}" {{', '  node [shape=record, fontname="Courier", fontsize=10];',
             '  edge [fontname="Helvetica", fontsize=9];', f'  label="{name}"; labelloc=t;']
    for b in cfg.blocks:
        body = "\\l".join(_dot_escape(str(i)) for i in b.instrs) + "\\l"
        lines.append(f'  {b.name} [label="{{{b.name}|{body}}}"];')
    for b in cfg.blocks:
        for s, kind in b.succs:
            lines.append(f'  {b.name} -> {s}' + (f' [label="{kind}"]' if kind else "") + ";")
    lines.append("}")
    return "\n".join(lines) + "\n"
