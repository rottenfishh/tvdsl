"""
funny_regalloc.py — граф конфликтов (interference graph) и жадная раскраска (HW4).

Зачем: кодогенерации нужно разложить временные по ячейкам (регистрам / слотам локальных
переменных JVM). Две временные можно положить в одну ячейку, если они никогда не живы
одновременно. Раскраска графа: цвет = номер ячейки.

Построение (лекция 6, «Распределение регистров»):
    в каждой точке записи x := ...  x конфликтует со всеми переменными, живыми ПОСЛЕ команды
    (кроме самого x). Исключение — копия x := y: x и y хранят одно значение, ребро не нужно
    (тогда раскраска может положить их в одну ячейку и копия исчезнет).
    Результаты одного call x1, x2 := call f() пишутся одновременно — конфликтуют между собой.

Узлы графа — временные t1, t2, ... (переменные программы у JVM уже имеют свои слоты).
С флагом --color-all красим и переменные программы (кроме параметров — их места
задаёт соглашение о вызове, но в графе они участвуют, чтобы учесть конфликты).

Жадная раскраска:
    1) узлы сортируем по убыванию степени (у кого больше соседей — тот сложнее, красим первым),
       при равенстве — по имени (результат воспроизводим);
    2) каждому узлу — наименьший цвет, которого нет у уже покрашенных соседей.
Это эвристика: оптимум не гарантирован (задача NP-трудная), но число цветов не больше
максимальной степени + 1.

Если задано число регистров K (--regs=K), узлы с цветом >= K — «сброс» (spill): им ячейки
не хватило, кодогенератор хранит их в памяти (для JVM — просто в дополнительных слотах).
"""
from dataclasses import dataclass, field

from funny_ir import Copy, Call
from funny_cfg import build_cfg, liveness, live_after_each


@dataclass
class Interference:
    function: str
    nodes: list                                     # узлы в порядке появления
    edges: set = field(default_factory=set)         # {(a, b)} с a < b
    colors: dict = field(default_factory=dict)      # узел -> цвет 0, 1, ...
    order: list = field(default_factory=list)       # порядок раскраски
    spilled: list = field(default_factory=list)

    def neighbors(self, v):
        return sorted({b for a, b in self.edges if a == v} | {a for a, b in self.edges if b == v})

    def degree(self, v):
        return len(self.neighbors(v))

    @property
    def num_colors(self):
        return max(self.colors.values()) + 1 if self.colors else 0

    def is_valid(self):
        """Соседи покрашены в разные цвета, покрашены все узлы."""
        return all(v in self.colors for v in self.nodes) and \
            all(self.colors[a] != self.colors[b] for a, b in self.edges)


def build_interference(fn, color_all=False):
    """Граф конфликтов для функции IR (обычно — после оптимизаций)."""
    if color_all:
        params = {n for n, _ in fn.params}
        candidates = lambda v: v not in params      # noqa: E731
    else:
        candidates = fn.is_temp
    cfg = build_cfg(fn)
    liveness(cfg)
    nodes, edges = [], set()

    def add_node(v):
        if candidates(v) and v not in nodes:
            nodes.append(v)

    def add_edge(a, b):
        if a != b and candidates(a) and candidates(b):
            edges.add((min(a, b), max(a, b)))

    for b in cfg.blocks:
        after = live_after_each(b)
        for ins, live in zip(b.instrs, after):
            for v in ins.defs() + ins.uses():
                add_node(v)
            for d in ins.defs():
                for v in live:
                    if isinstance(ins, Copy) and v == ins.src:
                        continue
                    add_edge(d, v)
            if isinstance(ins, Call):
                for x in ins.dsts:
                    for y in ins.dsts:
                        add_edge(x, y)
    return Interference(fn.name, nodes, edges)


def greedy_color(graph, regs=None):
    """Жадная раскраска по убыванию степени. regs — число регистров (для отчёта о сбросах)."""
    graph.order = sorted(graph.nodes, key=lambda v: (-graph.degree(v), _natural(v)))
    graph.colors = {}
    for v in graph.order:
        taken = {graph.colors[u] for u in graph.neighbors(v) if u in graph.colors}
        c = 0
        while c in taken:
            c += 1
        graph.colors[v] = c
    graph.spilled = [v for v in graph.order if regs is not None and graph.colors[v] >= regs]
    return graph


def _natural(name):
    """t2 < t10: сравниваем буквы, потом число."""
    head = name.rstrip("0123456789")
    tail = name[len(head):]
    return (head, int(tail) if tail else -1)


def allocate(fn, color_all=False, regs=None):
    return greedy_color(build_interference(fn, color_all), regs)


# ---------- вывод ----------

def format_interference(g):
    lines = [f"interference {g.function}: узлов {len(g.nodes)}, рёбер {len(g.edges)}, цветов {g.num_colors}"]
    for v in sorted(g.nodes, key=_natural):
        nb = ", ".join(sorted(g.neighbors(v), key=_natural)) or "—"
        lines.append(f"  {v:<6} цвет {g.colors.get(v, '?')}   соседи: {nb}")
    if g.order:
        lines.append("  порядок раскраски: " + ", ".join(g.order))
    by_color = {}
    for v in sorted(g.nodes, key=_natural):
        by_color.setdefault(g.colors.get(v), []).append(v)
    for c in sorted(k for k in by_color if k is not None):
        lines.append(f"  r{c}: {', '.join(by_color[c])}")
    if g.spilled:
        lines.append("  сброс (spill): " + ", ".join(g.spilled))
    return "\n".join(lines)


PALETTE = ["#8ecae6", "#ffb703", "#90be6d", "#f28482", "#cdb4db", "#f9c74f", "#43aa8b",
           "#f8961e", "#a2d2ff", "#bdb2ff", "#ffadad", "#caffbf"]


def interference_to_dot(g):
    lines = [f'graph "{g.function}" {{', '  node [shape=circle, style=filled, fontname="Helvetica"];',
             f'  label="{g.function}: {g.num_colors} цв."; labelloc=t;']
    for v in sorted(g.nodes, key=_natural):
        c = g.colors.get(v)
        color = PALETTE[c % len(PALETTE)] if c is not None else "white"
        extra = ", peripheries=2" if v in g.spilled else ""
        lines.append(f'  "{v}" [label="{v}\\nr{c}", fillcolor="{color}"{extra}];')
    for a, b in sorted(g.edges, key=lambda e: (_natural(e[0]), _natural(e[1]))):
        lines.append(f'  "{a}" -- "{b}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def interference_to_json(g):
    return {"function": g.function, "nodes": g.nodes,
            "edges": [list(e) for e in sorted(g.edges)],
            "colors": g.colors, "num_colors": g.num_colors, "spilled": g.spilled}
