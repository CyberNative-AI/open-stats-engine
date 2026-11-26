"""Partialling out several high-dimensional fixed effects.

Algorithm and sources are recorded in docs/estimators/reghdfe.md:

- Singletons: observations alone in any fixed-effect group are dropped,
  repeatedly until none remain (Correia 2015, "Singletons, cluster-robust
  standard errors and fixed effects: a bad mix").
- Partialling: method of alternating projections with a symmetric Kaczmarz
  sweep (demean by FE 1..G then G-1..1), accelerated by conjugate gradient
  (Correia 2017, "Linear models with high-dimensional fixed effects: an
  efficient and feasible estimator"; Hernandez-Ramos, Escalante and Raydan
  2011 for CG on the alternating-projection operator).
- Stopping: Hestenes-Stiefel error estimate, sqrt(alpha_k * ||r_k||^2 /
  remaining), all columns jointly, tolerance 1e-8.
- Redundant fixed-effect levels: connected components of the bipartite
  graph of two fixed effects (Abowd, Creecy and Kramarz 2002, "mobility groups").
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .errors import StataError

TOL = 1e-8
MAXITER = 16000


def codes(values):
    """Group codes 0..n-1 for any array (numbers or strings)."""
    _, inv = np.unique(values, return_inverse=True)
    return inv.ravel()


def drop_singletons(fes):
    """Boolean keep-mask after repeatedly removing singleton groups."""
    n = len(fes[0])
    keep = np.ones(n, dtype=bool)
    while True:
        idx = np.nonzero(keep)[0]
        bad = np.zeros(len(idx), dtype=bool)
        for f in fes:
            _, inv, cnt = np.unique(f[idx], return_inverse=True, return_counts=True)
            bad |= cnt[inv] == 1
        if not bad.any():
            return keep
        keep[idx[bad]] = False


class Absorber:
    def __init__(self, groups):
        """groups: list of integer code arrays (0..n_g-1) over the final sample."""
        self.groups = groups
        self.counts = [np.bincount(g).astype(np.float64) for g in groups]

    def _demean(self, A, k):
        g, c = self.groups[k], self.counts[k]
        out = np.empty_like(A)
        for j in range(A.shape[1]):
            out[:, j] = A[:, j] - (np.bincount(g, A[:, j], minlength=len(c)) / c)[g]
        return out

    def sweep(self, A):
        """Symmetric Kaczmarz: forward over the fixed effects, then back."""
        order = list(range(len(self.groups)))
        for k in order:
            A = self._demean(A, k)
        for k in order[::-1][1:]:
            A = self._demean(A, k)
        return A

    def partial(self, Y):
        """Return (partialled Y, iterations). Y is (N, p)."""
        if len(self.groups) == 1:
            return self._demean(Y, 0), 1
        y = Y.copy()
        r = y - self.sweep(y)
        u = r.copy()
        ssr = np.sum(r * r, axis=0)
        remaining = np.sum(y * y, axis=0)
        live = remaining > 0
        for it in range(1, MAXITER + 1):
            Au = u - self.sweep(u)
            uAu = np.sum(u * Au, axis=0)
            alpha = np.where(uAu > 0, ssr / np.where(uAu > 0, uAu, 1.0), 0.0)
            step = alpha * ssr
            remaining = remaining - step
            y = y - alpha * u
            r = r - alpha * Au
            ssr_old = ssr
            ssr = np.sum(r * r, axis=0)
            err = np.zeros_like(step)
            ok = live & (remaining > 0)
            err[ok] = np.sqrt(step[ok] / remaining[ok])
            if np.max(err) <= TOL:
                return y, it
            beta = np.where(ssr_old > 0, ssr / np.where(ssr_old > 0, ssr_old, 1.0), 0.0)
            u = r + beta * u
        raise StataError(f"ose: fixed-effect partialling did not converge in {MAXITER} iterations", 430)


def components(a, b):
    """Connected components of the bipartite graph linking groups of a and b."""
    na, nb = int(a.max()) + 1, int(b.max()) + 1
    A = coo_matrix((np.ones(len(a)), (a, b + na)), shape=(na + nb, na + nb))
    return connected_components(A, directed=False)[0]


def nested_in(g, cl):
    """True if every group of g lies inside a single cluster."""
    pairs = np.unique(np.stack([g, cl], axis=1), axis=0)
    return len(pairs) == int(g.max()) + 1


def absorbed_dof(groups, cluster):
    """Rows (categories, redundant, coefs, mark) for the absorbed-DoF table.

    mark is '*' (nested in the cluster variable), '?' (redundancy is a lower
    bound) or ''. Rules learned from published logs, see the estimator record:
    nested FEs are fully redundant; among the rest, the first loses one level
    to the constant only if some FE was nested (otherwise the constant is the
    first FE's own), the second loses its connected components with the first
    (exact), later ones the largest component count against any earlier
    non-nested FE (a lower bound, marked '?').
    """
    rows = []
    nested = [cluster is not None and nested_in(g, cluster) for g in groups]
    any_nested = any(nested)
    kept = []
    for g, is_n in zip(groups, nested):
        n = int(g.max()) + 1
        if is_n:
            rows.append([n, n, 0, "*"])
            continue
        if not kept:
            red, mark = (1 if any_nested else 0), ""
        elif len(kept) == 1:
            red, mark = components(kept[0], g), ""
        else:
            red, mark = max(components(k, g) for k in kept), "?"
        kept.append(g)
        rows.append([n, red, n - red, mark])
    return rows
