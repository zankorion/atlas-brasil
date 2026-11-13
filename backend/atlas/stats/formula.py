"""Motor de fórmulas para indicadores derivados e personalizados.

- Sintaxe: expressões aritméticas sobre identificadores de indicadores do catálogo.
  Operadores: + - * / ** e parênteses. Funções: pct(a, b), part(a, b), lag(x, n), var(x, n),
  ultimo(x), real(x), log(x).
- Validação de unidades: soma/subtração exigem a mesma dimensão; produto/divisão
  compõem dimensões (R$ / pessoas -> R$ por pessoa).
- Ausências propagam: qualquer operando ausente gera resultado ausente.
- Divisão por zero gera ausência (contada em `div_zero`), nunca infinito nem zero.
- Periodicidades diferentes não são combinadas automaticamente.

A análise usa o módulo `ast` com lista branca de nós — nada é executado via eval.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Protocol

import polars as pl


class FormulaError(ValueError):
    """Erro de sintaxe, de unidade ou de referência — a mensagem é exibida ao usuário."""


# ---------------------------------------------------------------------- unidades
@dataclass(frozen=True)
class UnitT:
    dims: tuple[tuple[str, int], ...] = ()
    percent: bool = False

    @staticmethod
    def of(dims: dict | None, percent: bool = False) -> "UnitT":
        return UnitT(tuple(sorted((k, int(v)) for k, v in (dims or {}).items() if v)), percent)

    def combine(self, other: "UnitT", sign: int) -> "UnitT":
        d = dict(self.dims)
        for k, v in other.dims:
            d[k] = d.get(k, 0) + sign * v
        return UnitT.of(d)

    def power(self, n: int) -> "UnitT":
        return UnitT.of({k: v * n for k, v in self.dims})

    @property
    def dimensionless(self) -> bool:
        return not self.dims

    def label(self) -> str:
        names = {"BRL": "R$", "pessoa": "habitante", "km2": "km²", "ha": "ha", "agencia": "agências",
                 "domicilio": "domicílios", "estab": "estabelecimentos", "USD": "US$"}
        if self.dimensionless:
            return "%" if self.percent else "razão (adimensional)"
        num = [names.get(k, k) + (f"^{v}" if v > 1 else "") for k, v in self.dims if v > 0]
        den = [names.get(k, k) + (f"^{-v}" if v < -1 else "") for k, v in self.dims if v < 0]
        s = "·".join(num) or "1"
        return s + ("/" + "·".join(den) if den else "")


# ------------------------------------------------------------------------ dados
class Loader(Protocol):
    def info(self, indicator_id: str) -> dict | None: ...
    def load(self, indicator_id: str, level: str, periods: list[str] | None, codes: list[str] | None) -> pl.DataFrame: ...
    def deflator(self, freq: str, stock_flow: str) -> tuple[dict[str, float], str]: ...


@dataclass
class Frame:
    """Resultado parcial: tabela (code, period, value) ou escalar."""

    df: pl.DataFrame | None  # None => escalar
    unit: UnitT
    scalar: float | None = None
    freq: str | None = None
    broadcast: bool = False  # sem coluna de período (função ultimo)
    stock_flow: str = "na"
    nominal: bool = False

    @property
    def is_scalar(self) -> bool:
        return self.df is None


@dataclass
class Result:
    df: pl.DataFrame
    unit: UnitT
    freq: str
    components: list[str]
    div_zero: int = 0
    notes: list[str] = field(default_factory=list)
    out_of_range: int = 0
    nominal: bool = False
    stock_flow: str = "na"


FUNCS = {"pct", "part", "lag", "var", "ultimo", "real", "log"}
MAX_DEPTH = 6


def shift_period(period: str, n: int) -> str:
    """Desloca um período 'AAAA' ou 'AAAA-MM' em n passos."""
    if "-" in period:
        y, m = map(int, period.split("-"))
        t = y * 12 + (m - 1) + n
        return f"{t // 12}-{t % 12 + 1:02d}"
    return str(int(period) + n)


def parse(expr: str) -> ast.Expression:
    expr = (expr or "").strip()
    if not expr:
        raise FormulaError("A fórmula está vazia.")
    if len(expr) > 500:
        raise FormulaError("Fórmula muito longa (máximo de 500 caracteres).")
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Erro de sintaxe na posição {e.offset}: verifique parênteses e operadores.") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd,
                             ast.BinOp, ast.UnaryOp, ast.Name)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
            continue
        raise FormulaError("Elemento não permitido na fórmula. Use indicadores, números, + - * / ** e as funções "
                           + ", ".join(sorted(FUNCS)) + ".")
    return tree


def references(expr: str) -> list[str]:
    tree = parse(expr)
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in FUNCS})


class Evaluator:
    def __init__(self, loader: Loader, level: str, periods: list[str] | None, codes: list[str] | None):
        self.loader, self.level, self.periods, self.codes = loader, level, periods, codes
        self.components: set[str] = set()
        self.div_zero = 0
        self.out_of_range = 0
        self.notes: list[str] = []

    # -- folhas
    def indicator(self, name: str, periods: list[str] | None, depth: int) -> Frame:
        info = self.loader.info(name)
        if info is None:
            raise FormulaError(f"Indicador desconhecido: “{name}”.")
        if info.get("status") == "planejado":
            raise FormulaError(f"O indicador “{name}” ainda não possui dados integrados.")
        if info.get("formula"):
            if depth >= MAX_DEPTH:
                raise FormulaError("Fórmulas aninhadas em excesso.")
            sub = Evaluator(self.loader, self.level, periods, self.codes)
            f = sub.eval(parse(info["formula"]).body, depth + 1)
            self.components |= sub.components
            self.div_zero += sub.div_zero
            self.out_of_range += sub.out_of_range
            f.unit = UnitT.of(info["dims"], info["percent"])  # unidade declarada no catálogo
            f.stock_flow = info.get("stock_flow", f.stock_flow)
            f.nominal = info.get("value_kind") == "nominal"
            return f
        self.components.add(name)
        df = self.loader.load(name, self.level, periods, self.codes)
        return Frame(df, UnitT.of(info["dims"], info["percent"]), freq=info["frequency"],
                     stock_flow=info.get("stock_flow", "na"), nominal=info.get("value_kind") == "nominal")

    # -- operações
    def _join(self, a: Frame, b: Frame) -> tuple[pl.DataFrame, Frame]:
        if a.broadcast and b.broadcast:
            df = a.df.join(b.df.rename({"value": "value_b"}), on="code", how="full", coalesce=True)
            return df, Frame(None, a.unit, freq=a.freq or b.freq, broadcast=True)
        if a.broadcast or b.broadcast:
            left, right = (b, a) if a.broadcast else (a, b)
            df = left.df.join(right.df.rename({"value": "value_o"}), on="code", how="left")
            if a.broadcast:
                df = df.rename({"value": "value_b", "value_o": "value"})
            else:
                df = df.rename({"value_o": "value_b"})
            return df, Frame(None, a.unit, freq=left.freq)
        if a.freq != b.freq:
            raise FormulaError("Os indicadores têm periodicidades diferentes (anual × mensal); o Atlas não as combina "
                               "automaticamente. Use indicadores de mesma periodicidade.")
        df = a.df.join(b.df.rename({"value": "value_b"}), on=["code", "period"], how="full", coalesce=True)
        return df, Frame(None, a.unit, freq=a.freq)

    def binop(self, op: str, a: Frame, b: Frame) -> Frame:
        # unidades
        if op in ("+", "-"):
            if a.unit.dims != b.unit.dims:
                raise FormulaError(f"Unidades incompatíveis em “{op}”: {a.unit.label()} e {b.unit.label()}.")
            unit = UnitT(a.unit.dims, a.unit.percent and b.unit.percent) if not (a.is_scalar or b.is_scalar) else (
                b.unit if a.is_scalar else a.unit)
        elif op == "*":
            unit = b.unit if a.is_scalar else a.unit if b.is_scalar else a.unit.combine(b.unit, 1)
        else:  # "/"
            unit = a.unit if b.is_scalar else a.unit.combine(b.unit, -1)
        nominal = (a.nominal != b.nominal) if op in ("*", "/") else (a.nominal or b.nominal)
        sf = a.stock_flow if not a.is_scalar else b.stock_flow
        # valores
        if a.is_scalar and b.is_scalar:
            x, y = a.scalar, b.scalar
            if op == "/" and y == 0:
                raise FormulaError("Divisão por zero entre constantes.")
            v = x + y if op == "+" else x - y if op == "-" else x * y if op == "*" else x / y
            return Frame(None, unit, scalar=v)
        if a.is_scalar or b.is_scalar:
            fr, k = (b, a.scalar) if a.is_scalar else (a, b.scalar)
            c = pl.col("value")
            if op == "+":
                e = c + k
            elif op == "*":
                e = c * k
            elif op == "-":
                e = (k - c) if a.is_scalar else (c - k)
            elif a.is_scalar:  # k / coluna
                self.div_zero += int(fr.df.filter(c == 0).height)
                e = pl.when(c == 0).then(None).otherwise(k / c)
            else:
                if k == 0:
                    raise FormulaError("Divisão por zero (constante).")
                e = c / k
            return Frame(fr.df.with_columns(e.alias("value")), unit, freq=fr.freq, broadcast=fr.broadcast,
                         stock_flow=fr.stock_flow, nominal=fr.nominal)
        df, meta = self._join(a, b)
        x, y = pl.col("value"), pl.col("value_b")
        if op == "/":
            self.div_zero += int(df.filter((y == 0) & x.is_not_null()).height)
            e = pl.when(y == 0).then(None).otherwise(x / y)
        else:
            e = x + y if op == "+" else x - y if op == "-" else x * y
        df = df.with_columns(e.alias("value")).drop("value_b")
        return Frame(df, unit, freq=meta.freq, broadcast=meta.broadcast, stock_flow=sf, nominal=nominal)

    # -- funções
    def _name_arg(self, node: ast.AST, fn: str) -> str:
        if not isinstance(node, ast.Name) or node.id in FUNCS:
            raise FormulaError(f"O primeiro argumento de {fn}() deve ser o identificador de um indicador (ou real(indicador)).")
        return node.id

    def _int_arg(self, node: ast.AST, fn: str) -> int:
        if not (isinstance(node, ast.Constant) and isinstance(node.value, int) and 1 <= node.value <= 60):
            raise FormulaError(f"O segundo argumento de {fn}() deve ser um inteiro entre 1 e 60.")
        return node.value

    def _series_arg(self, node: ast.AST, fn: str) -> tuple[str, bool]:
        """Aceita `indicador` ou `real(indicador)` como primeiro argumento de lag()/var()."""
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "real"
                and len(node.args) == 1 and isinstance(node.args[0], ast.Name)):
            return node.args[0].id, True
        return self._name_arg(node, fn), False

    def lagged(self, name: str, n: int, depth: int, real: bool = False) -> Frame:
        src = None if self.periods is None else [shift_period(p, -n) for p in self.periods]
        f = self.indicator(name, src, depth)
        if real:
            f = self.deflate(f)  # deflaciona pelo período de origem, antes de deslocar o rótulo
        df = f.df.with_columns(pl.col("period").map_elements(lambda p: shift_period(p, n), return_dtype=pl.String))
        return Frame(df, f.unit, freq=f.freq, stock_flow=f.stock_flow, nominal=f.nominal)

    def call(self, node: ast.Call, depth: int) -> Frame:
        fn, args = node.func.id, node.args
        if fn in ("pct", "part"):
            if len(args) != 2:
                raise FormulaError(f"{fn}(a, b) exige dois argumentos.")
            a, b = self.eval(args[0], depth), self.eval(args[1], depth)
            if a.unit.dims != b.unit.dims:
                raise FormulaError(f"{fn}(a, b) exige a mesma unidade nos dois argumentos: {a.unit.label()} e {b.unit.label()}.")
            r = self.binop("*", self.binop("/", a, b), Frame(None, UnitT(), scalar=100.0))
            r.unit, r.nominal = UnitT((), True), False
            if fn == "part" and not r.is_scalar:
                # Participação de uma parte no todo só tem sentido entre 0 e 100 %. Fora disso (parte negativa ou maior
                # que o total, por registros contábeis negativos na fonte) o resultado é ausente, e a ocorrência é contada.
                v = pl.col("value")
                bad = v.is_not_null() & ((v < -1e-9) | (v > 100 + 1e-6))
                self.out_of_range += int(r.df.filter(bad).height)
                r.df = r.df.with_columns(pl.when(bad).then(None).otherwise(v).alias("value"))
            return r
        if fn in ("lag", "var"):
            if len(args) not in (1, 2):
                raise FormulaError(f"{fn}(x, n) exige um indicador e, opcionalmente, o número de períodos.")
            name, real = self._series_arg(args[0], fn)
            n = self._int_arg(args[1], fn) if len(args) == 2 else 1
            prev = self.lagged(name, n, depth, real)
            if fn == "lag":
                return prev
            cur = self.indicator(name, self.periods, depth)
            if real:
                cur = self.deflate(cur)
            ratio = self.binop("/", cur, prev)
            r = self.binop("*", self.binop("-", ratio, Frame(None, UnitT(), scalar=1.0)), Frame(None, UnitT(), scalar=100.0))
            r.unit, r.nominal = UnitT((), True), False
            return r
        if fn == "ultimo":
            if len(args) != 1:
                raise FormulaError("ultimo(x) exige um argumento.")
            f = self.indicator(self._name_arg(args[0], fn), None, depth)
            df = (f.df.filter(pl.col("value").is_not_null()).sort("period")
                  .group_by("code", maintain_order=True).agg(pl.col("value").last()))
            return Frame(df, f.unit, freq=f.freq, broadcast=True, stock_flow=f.stock_flow, nominal=f.nominal)
        if fn == "real":
            if len(args) != 1:
                raise FormulaError("real(x) exige um argumento.")
            f = self.eval(args[0], depth)
            return self.deflate(f)
        if fn == "log":
            if len(args) != 1:
                raise FormulaError("log(x) exige um argumento.")
            f = self.eval(args[0], depth)
            if f.is_scalar:
                raise FormulaError("log() de constante não é suportado.")
            c = pl.col("value")
            return Frame(f.df.with_columns(pl.when(c > 0).then(c.log()).otherwise(None).alias("value")),
                         UnitT(), freq=f.freq, broadcast=f.broadcast)
        raise FormulaError(f"Função desconhecida: {fn}.")

    def deflate(self, f: Frame) -> Frame:
        if f.is_scalar or f.broadcast:
            raise FormulaError("real() deve ser aplicado a um indicador monetário com período.")
        if dict(f.unit.dims).get("BRL", 0) != 1:
            raise FormulaError(f"real() só se aplica a valores em reais; a expressão tem unidade {f.unit.label()}.")
        if not f.nominal:
            raise FormulaError("real() só se aplica a valores nominais (a expressão já é real ou não é monetária).")
        factors, base = self.loader.deflator(f.freq or "A", f.stock_flow)
        d = pl.DataFrame({"period": list(factors.keys()), "_k": list(factors.values())},
                         schema={"period": pl.String, "_k": pl.Float64})
        df = f.df.join(d, on="period", how="left").with_columns((pl.col("value") * pl.col("_k")).alias("value")).drop("_k")
        self.notes.append(f"Valores deflacionados pelo IPCA, a preços de {base}.")
        return Frame(df, f.unit, freq=f.freq, stock_flow=f.stock_flow, nominal=False)

    # -- despacho
    def eval(self, node: ast.AST, depth: int = 0) -> Frame:
        if isinstance(node, ast.Constant):
            return Frame(None, UnitT(), scalar=float(node.value))
        if isinstance(node, ast.Name):
            return self.indicator(node.id, self.periods, depth)
        if isinstance(node, ast.UnaryOp):
            f = self.eval(node.operand, depth)
            if isinstance(node.op, ast.UAdd):
                return f
            return self.binop("*", f, Frame(None, UnitT(), scalar=-1.0))
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Pow):
                base = self.eval(node.left, depth)
                if not (isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float))):
                    raise FormulaError("O expoente deve ser uma constante numérica.")
                n = node.right.value
                if not base.unit.dimensionless and int(n) != n:
                    raise FormulaError("Expoente fracionário só é permitido para grandezas adimensionais.")
                if base.is_scalar:
                    return Frame(None, UnitT(), scalar=base.scalar**n)
                df = base.df.with_columns(pl.col("value").pow(n).alias("value"))
                return Frame(df, base.unit.power(int(n)) if int(n) == n else base.unit, freq=base.freq,
                             broadcast=base.broadcast)
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(node.op)]
            return self.binop(op, self.eval(node.left, depth), self.eval(node.right, depth))
        if isinstance(node, ast.Call):
            return self.call(node, depth)
        raise FormulaError("Expressão inválida.")


def evaluate(expr: str, loader: Loader, level: str, periods: list[str] | None = None,
             codes: list[str] | None = None) -> Result:
    tree = parse(expr)
    ev = Evaluator(loader, level, periods, codes)
    f = ev.eval(tree.body)
    if f.is_scalar:
        raise FormulaError("A fórmula precisa referenciar ao menos um indicador.")
    if f.broadcast:
        raise FormulaError("ultimo(x) deve ser combinado com um indicador que tenha período.")
    df = f.df.with_columns(
        pl.when(pl.col("value").is_finite()).then(pl.col("value")).otherwise(None).alias("value"))
    if periods is not None:
        df = df.filter(pl.col("period").is_in(periods))
    return Result(df.select("code", "period", "value"), f.unit, f.freq or "A", sorted(ev.components),
                  ev.div_zero, ev.notes, out_of_range=ev.out_of_range, nominal=f.nominal, stock_flow=f.stock_flow)


def check_units(expr: str, loader: Loader) -> UnitT:
    """Valida sintaxe, referências e unidades sem carregar dados."""

    class _Empty:
        def __init__(self, inner):
            self.inner = inner

        def info(self, i):
            return self.inner.info(i)

        def load(self, *_):
            return pl.DataFrame(schema={"code": pl.String, "period": pl.String, "value": pl.Float64})

        def deflator(self, *_):
            return {}, "—"

    tree = parse(expr)
    f = Evaluator(_Empty(loader), "BR", None, None).eval(tree.body)
    if f.is_scalar:
        raise FormulaError("A fórmula precisa referenciar ao menos um indicador.")
    return f.unit
