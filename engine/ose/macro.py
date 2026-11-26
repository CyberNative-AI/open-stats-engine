"""Macro expansion: `local', $global, ${global}, `=exp', `: extended function'."""
import re

from .errors import StataError, Unsupported

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class MacroExpander:
    def __init__(self, interp):
        self.it = interp

    def expand(self, s):
        out, i = self._expand(s, 0, top=True)
        return out

    def _expand(self, s, i, top):
        out = []
        n = len(s)
        while i < n:
            c = s[i]
            if c == "`":
                if i + 1 < n and s[i + 1] == '"':
                    out.append('`"')
                    i += 2
                    continue
                inner, j = self._expand(s, i + 1, top=False)
                out.append(self._lookup(inner))
                i = j
                continue
            if c == "'" and not top:
                return "".join(out), i + 1
            if c == "$":
                if i + 1 < n and s[i + 1] == "{":
                    j = s.find("}", i + 2)
                    if j != -1:
                        name, _ = self._expand(s[i + 2:j], 0, top=True)
                        out.append(self.it.globals.get(name.strip(), ""))
                        i = j + 1
                        continue
                m = NAME.match(s, i + 1)
                if m:
                    out.append(self.it.globals.get(m.group(0)[:32], ""))
                    i = m.end()
                    continue
            if c == "\\" and i + 1 < n and s[i + 1] in "`$":
                out.append(s[i + 1])
                i += 2
                continue
            out.append(c)
            i += 1
        if not top:
            # unmatched opening quote: keep text as typed
            return "`" + "".join(out), i
        return "".join(out), i

    def _lookup(self, inner):
        L = self.it.locals
        if inner.startswith("="):
            v = self.it.eval_scalar_expr(inner[1:])
            return self.it.num_to_macro(v) if not isinstance(v, str) else v
        if inner.startswith(":"):
            return self.it.extended_function(inner[1:].strip())
        if inner.startswith("++") or inner.startswith("--"):
            name = inner[2:]
            v = _num(L.get(name, "")) + (1 if inner[0] == "+" else -1)
            L[name] = self.it.num_to_macro(v)
            return L[name]
        if inner.endswith("++") or inner.endswith("--"):
            name = inner[:-2]
            old = L.get(name, "")
            L[name] = self.it.num_to_macro(_num(old) + (1 if inner[-1] == "+" else -1))
            return old
        return L.get(inner, "")


def _num(s):
    try:
        return float(s) if s.strip() else 0.0
    except ValueError:
        raise StataError(f"{s} invalid number", 198)
