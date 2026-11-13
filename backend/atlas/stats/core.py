"""Estatísticas do Laboratório: correlação, regressão, desigualdade e classificação de mapas.

Todas as funções recebem vetores já limpos de ausências e devolvem também o
tamanho amostral, para que a interface sempre exiba n.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy import stats as sps


def _f(x) -> float | None:
    x = float(x)
    return None if (math.isnan(x) or math.isinf(x)) else x


def describe(v: Sequence[float]) -> dict:
    a = np.asarray(v, dtype=float)
    if a.size == 0:
        return {"n": 0}
    q = np.percentile(a, [10, 25, 50, 75, 90])
    return {
        "n": int(a.size), "mean": _f(a.mean()), "std": _f(a.std(ddof=1)) if a.size > 1 else None,
        "min": _f(a.min()), "p10": _f(q[0]), "p25": _f(q[1]), "median": _f(q[2]),
        "p75": _f(q[3]), "p90": _f(q[4]), "max": _f(a.max()),
    }


def correlation(x: Sequence[float], y: Sequence[float]) -> dict:
    """Pearson e Spearman com valor-p bilateral. Associação estatística — não causalidade."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = int(x.size)
    out: dict = {"n": n, "pearson": None, "spearman": None}
    if n < 3 or np.all(x == x[0]) or np.all(y == y[0]):
        out["note"] = "Amostra insuficiente ou variável constante."
        return out
    pr = sps.pearsonr(x, y)
    sr = sps.spearmanr(x, y)
    out["pearson"] = {"r": _f(pr.statistic), "p": _f(pr.pvalue)}
    out["spearman"] = {"rho": _f(sr.statistic), "p": _f(sr.pvalue)}
    return out


def ols(x: Sequence[float], y: Sequence[float]) -> dict | None:
    """Regressão linear simples por mínimos quadrados: y = a + b·x."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = int(x.size)
    if n < 3 or np.all(x == x[0]):
        return None
    r = sps.linregress(x, y)
    resid = y - (r.intercept + r.slope * x)
    return {
        "n": n, "intercept": _f(r.intercept), "slope": _f(r.slope), "r2": _f(r.rvalue**2),
        "p_slope": _f(r.pvalue), "se_slope": _f(r.stderr), "se_intercept": _f(r.intercept_stderr),
        "rmse": _f(math.sqrt(float(np.sum(resid**2)) / (n - 2))),
    }


def gini(values: Sequence[float], weights: Sequence[float] | None = None) -> float | None:
    """Gini de valores não negativos (opcionalmente ponderado, ex.: pela população)."""
    v = np.asarray(values, float)
    w = np.ones_like(v) if weights is None else np.asarray(weights, float)
    ok = (v >= 0) & (w > 0)
    v, w = v[ok], w[ok]
    if v.size < 2 or float(np.sum(v * w)) == 0:
        return None
    order = np.argsort(v)
    v, w = v[order], w[order]
    cw = np.cumsum(w) / np.sum(w)
    cv = np.cumsum(v * w) / np.sum(v * w)
    cw0, cv0 = np.insert(cw, 0, 0.0), np.insert(cv, 0, 0.0)
    area = float(np.sum((cw0[1:] - cw0[:-1]) * (cv0[1:] + cv0[:-1]) / 2))
    return _f(1 - 2 * area)


def theil(values: Sequence[float], weights: Sequence[float] | None = None) -> float | None:
    """Índice de Theil-T de valores positivos."""
    v = np.asarray(values, float)
    w = np.ones_like(v) if weights is None else np.asarray(weights, float)
    ok = (v > 0) & (w > 0)
    v, w = v[ok], w[ok]
    if v.size < 2:
        return None
    w = w / w.sum()
    mu = float(np.sum(w * v))
    return _f(np.sum(w * (v / mu) * np.log(v / mu)))


def inequality(values: Sequence[float], weights: Sequence[float] | None = None) -> dict:
    v = np.asarray(values, float)
    d = describe(v)
    out = {"n": d["n"], "gini": gini(values, weights), "theil": theil(values, weights)}
    if d["n"] > 1 and d.get("mean"):
        out["cv"] = _f(d["std"] / d["mean"]) if d["mean"] else None
        out["p90_p10"] = _f(d["p90"] / d["p10"]) if d["p10"] and d["p10"] > 0 else None
        out["max_min"] = _f(d["max"] / d["min"]) if d["min"] and d["min"] > 0 else None
    return out


def gini_grouped(counts: Sequence[float], totals: Sequence[float]) -> float | None:
    """Gini a partir de dados agrupados em classes ordenadas (curva de Lorenz, regra do trapézio).

    Supõe igualdade dentro de cada classe — é um limite inferior do Gini verdadeiro.
    Exige ao menos 3 classes com unidades.
    """
    c, t = np.asarray(counts, float), np.asarray(totals, float)
    ok = c > 0
    c, t = c[ok], t[ok]
    if c.size < 3 or t.sum() <= 0:
        return None
    order = np.argsort(t / c)
    c, t = c[order], t[order]
    cp = np.insert(np.cumsum(c) / c.sum(), 0, 0.0)
    ct = np.insert(np.cumsum(t) / t.sum(), 0, 0.0)
    return _f(1 - float(np.sum((cp[1:] - cp[:-1]) * (ct[1:] + ct[:-1]))))


def jenks_breaks(values: Sequence[float], k: int, max_n: int = 1200) -> list[float]:
    """Quebras naturais (Fisher-Jenks): limites que minimizam a variância dentro das classes.

    Programação dinâmica exata sobre os valores ordenados. Acima de `max_n` valores, o cálculo é feito
    sobre uma amostra de quantis equiespaçados (aproximação), para manter o tempo de resposta.
    """
    a = np.sort(np.asarray(values, dtype=float))
    if a.size > max_n:
        a = np.quantile(a, np.linspace(0, 1, max_n))
    n = a.size
    k = min(k, int(np.unique(a).size))
    if n == 0 or k < 2:
        return []
    c1 = np.concatenate([[0.0], np.cumsum(a)])
    c2 = np.concatenate([[0.0], np.cumsum(a * a)])

    def cost(i: np.ndarray, j: int) -> np.ndarray:
        """Soma dos quadrados dos desvios do segmento a[i:j], para um vetor de inícios i."""
        m = j - i
        s1 = c1[j] - c1[i]
        return (c2[j] - c2[i]) - s1 * s1 / m

    prev = np.full(n + 1, np.inf)
    for j in range(1, n + 1):
        prev[j] = cost(np.array([0]), j)[0]
    back = np.zeros((k, n + 1), dtype=int)
    for c in range(1, k):
        cur = np.full(n + 1, np.inf)
        for j in range(c + 1, n + 1):
            i = np.arange(c, j)
            tot = prev[i] + cost(i, j)
            b = int(np.argmin(tot))
            cur[j], back[c, j] = tot[b], i[b]
        prev = cur
    cuts, j = [], n
    for c in range(k - 1, 0, -1):
        j = int(back[c, j])
        cuts.append(j)
    out: list[float] = []
    for j in sorted(cuts):  # limite = maior valor da classe inferior
        b = float(a[j - 1])
        if not out or b > out[-1]:
            out.append(b)
    return out


def classify(values: Sequence[float], method: str = "quantis", k: int = 5) -> list[float]:
    """Limites internos de classe para mapas coropléticos (k classes -> k-1 limites)."""
    a = np.asarray([v for v in values if v is not None], float)
    if a.size == 0:
        return []
    if method == "jenks":
        return jenks_breaks(a, k)
    if method == "iguais":
        lo, hi = float(a.min()), float(a.max())
        br = [lo + (hi - lo) * i / k for i in range(1, k)]
    elif method == "geometrico":
        pos = a[a > 0]
        if pos.size == 0:
            return []
        lo, hi = math.log(float(pos.min())), math.log(float(pos.max()))
        br = [math.exp(lo + (hi - lo) * i / k) for i in range(1, k)]
    else:  # quantis
        br = [float(b) for b in np.percentile(a, [100 * i / k for i in range(1, k)])]
    out: list[float] = []
    for b in br:  # remove limites repetidos (distribuições com muitos empates)
        if not out or b > out[-1]:
            out.append(b)
    return out
