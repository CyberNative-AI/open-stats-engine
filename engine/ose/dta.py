"""Reader and writer for .dta dataset files.

Written from the publicly documented file layout (formats 113-115 and
117-119). Reading returns a Dataset; numeric columns become float64 with the
missing-value encoding described in missing.py.
"""
import itertools
import struct
import time

import numpy as np

from . import missing as M
from .dataset import Dataset, Variable

# --- numeric type tables -------------------------------------------------
NEW_TYPES = {65530: "byte", 65529: "int", 65528: "long", 65527: "float", 65526: "double", 32768: "strL"}
OLD_TYPES = {251: "byte", 252: "int", 253: "long", 254: "float", 255: "double"}
NP = {"byte": "i1", "int": "i2", "long": "i4", "float": "f4", "double": "f8"}
SIZE = {"byte": 1, "int": 2, "long": 4, "float": 4, "double": 8}
INT_MISS = {"byte": 101, "int": 32741, "long": 2147483621}


def _to_internal(raw, typ):
    """Convert a raw column array to float64 with internal missing codes."""
    if typ in INT_MISS:
        a = raw.astype(np.int64)
        out = a.astype(np.float64)
        m = a >= INT_MISS[typ]
        if m.any():
            code = a[m] - INT_MISS[typ]
            out[m] = [M.SYSMISS if c == 0 else M.EXT.get(chr(96 + int(c)), M.SYSMISS) for c in code]
        return out
    if typ == "float":
        bits = raw.view(np.uint32) if raw.dtype.byteorder in ("=", "<", "|") else raw.astype("<f4").view(np.uint32)
        out = raw.astype(np.float64)
        m = (bits & 0x7FFFFFFF) >= 0x7F000000
        m &= (bits >> 31) == 0
        if m.any():
            code = ((bits[m] - 0x7F000000) >> 11).astype(int)
            out[m] = [M.SYSMISS if c == 0 else M.EXT.get(chr(96 + c), M.SYSMISS) for c in code]
        return out
    # double: the file already uses our encoding; normalise anything beyond
    out = raw.astype(np.float64)
    out[np.isnan(out)] = M.SYSMISS
    return out


class _R:
    def __init__(self, buf):
        self.b = buf
        self.p = 0
        self.e = "<"

    def take(self, n):
        s = self.b[self.p:self.p + n]
        self.p += n
        return s

    def u(self, fmt):
        f = self.e + fmt
        v = struct.unpack_from(f, self.b, self.p)
        self.p += struct.calcsize(f)
        return v[0]

    def expect(self, tag):
        t = tag.encode()
        if self.b[self.p:self.p + len(t)] != t:
            raise ValueError(f"dta: expected {tag} at byte {self.p}")
        self.p += len(t)

    def cstr(self, n, enc):
        s = self.take(n)
        return s.split(b"\0", 1)[0].decode(enc, "replace")


def read_dta(path):
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:11] == b"<stata_dta>":
        return _read_new(buf)
    return _read_old(buf)


def _read_new(buf):
    r = _R(buf)
    r.expect("<stata_dta><header><release>")
    rel = int(r.take(3))
    if rel not in (117, 118, 119):
        raise ValueError(f"dta: unsupported release {rel}")
    r.expect("</release><byteorder>")
    r.e = "<" if r.take(3) == b"LSF" else ">"
    r.expect("</byteorder><K>")
    K = r.u("H") if rel < 119 else r.u("I")
    r.expect("</K><N>")
    N = r.u("I") if rel == 117 else r.u("Q")
    r.expect("</N><label>")
    enc = "latin-1" if rel == 117 else "utf-8"
    ll = r.u("B") if rel == 117 else r.u("H")
    label = r.take(ll).decode(enc, "replace")
    r.expect("</label><timestamp>")
    tl = r.u("B")
    timestamp = r.take(tl).decode(enc, "replace")
    r.expect("</timestamp></header><map>")
    r.take(14 * 8)
    r.expect("</map><variable_types>")
    codes = [r.u("H") for _ in range(K)]
    r.expect("</variable_types><varnames>")
    nlen = 33 if rel == 117 else 129
    names = [r.cstr(nlen, enc) for _ in range(K)]
    r.expect("</varnames><sortlist>")
    sw = "I" if rel == 119 else "H"
    sortlist = [r.u(sw) for _ in range(K + 1)]
    r.expect("</sortlist><formats>")
    flen = 49 if rel == 117 else 57
    fmts = [r.cstr(flen, enc) for _ in range(K)]
    r.expect("</formats><value_label_names>")
    vlnames = [r.cstr(nlen, enc) for _ in range(K)]
    r.expect("</value_label_names><variable_labels>")
    vllen = 81 if rel == 117 else 321
    vlabels = [r.cstr(vllen, enc) for _ in range(K)]
    r.expect("</variable_labels><characteristics>")
    chars = {}
    while r.b[r.p:r.p + 4] == b"<ch>":
        r.p += 4
        n = r.u("I")
        body = r.take(n)
        vn = body[:nlen].split(b"\0", 1)[0].decode(enc, "replace")
        cn = body[nlen:2 * nlen].split(b"\0", 1)[0].decode(enc, "replace")
        chars.setdefault(vn, {})[cn] = body[2 * nlen:].split(b"\0", 1)[0].decode(enc, "replace")
        r.expect("</ch>")
    r.expect("</characteristics><data>")
    types = []
    for c in codes:
        if c <= 2045:
            types.append(f"str{c}")
        else:
            types.append(NEW_TYPES[c])
    widths = [int(t[3:]) if t.startswith("str") and t != "strL" else (8 if t == "strL" else SIZE[t]) for t in types]
    rowlen = sum(widths)
    data = np.frombuffer(buf, dtype=np.uint8, count=N * rowlen, offset=r.p).reshape(N, rowlen) if N else np.zeros((0, rowlen), np.uint8)
    r.p += N * rowlen
    r.expect("</data><strls>")
    gso = {}
    while r.b[r.p:r.p + 3] == b"GSO":
        r.p += 3
        v = r.u("I")
        o = r.u("I") if rel == 117 else r.u("Q")
        t = r.u("B")
        ln = r.u("I")
        s = r.take(ln)
        if t == 130:
            s = s[:-1] if s.endswith(b"\0") else s
            s = s.decode(enc, "replace")
        gso[(v, o)] = s
    r.expect("</strls><value_labels>")
    vlabs = {}
    while r.b[r.p:r.p + 5] == b"<lbl>":
        r.p += 5
        r.u("I")
        lname = r.cstr(nlen, enc)
        r.take(3)
        vlabs[lname] = _read_vltable(r, enc)
        r.expect("</lbl>")
    cols = []
    off = 0
    for i, t in enumerate(types):
        w = widths[i]
        block = data[:, off:off + w]
        off += w
        if t == "strL":
            raw = np.ascontiguousarray(block)
            vals = []
            for row in raw:
                b8 = row.tobytes()
                if rel == 117:
                    v, o = struct.unpack(r.e + "II", b8)
                elif rel == 118:
                    v = struct.unpack(r.e + "H", b8[:2])[0] if r.e == "<" else struct.unpack(">H", b8[6:])[0]
                    o = int.from_bytes(b8[2:], "little") if r.e == "<" else int.from_bytes(b8[:6], "big")
                else:
                    v = int.from_bytes(b8[:3], "little") if r.e == "<" else int.from_bytes(b8[5:], "big")
                    o = int.from_bytes(b8[3:], "little") if r.e == "<" else int.from_bytes(b8[:5], "big")
                s = gso.get((v, o), "") if (v, o) != (0, 0) else ""
                vals.append(s if isinstance(s, str) else s.decode(enc, "replace"))
            arr = np.array(vals, dtype=object)
        elif t.startswith("str"):
            arr = np.array([bytes(x).split(b"\0", 1)[0].decode(enc, "replace") for x in block], dtype=object)
        else:
            raw = np.ascontiguousarray(block).view(r.e + NP[t]).reshape(N)
            arr = _to_internal(raw.astype("=" + NP[t]), t)
        cols.append(Variable(names[i], t, arr, fmts[i], vlabels[i], vlnames[i]))
    ds = Dataset(cols, label=label, value_labels=vlabs, chars=chars)
    ds.timestamp = timestamp
    ds.sortedby = [names[j - 1] for j in itertools.takewhile(bool, sortlist)][:K]  # 0 ends the list; Stata leaves junk after it
    return ds


def _read_vltable(r, enc):
    n = r.u("I")
    txtlen = r.u("I")
    offs = [r.u("I") for _ in range(n)]
    vals = [r.u("i") for _ in range(n)]
    txt = r.take(txtlen)
    out = {}
    for o, v in zip(offs, vals):
        out[v] = txt[o:].split(b"\0", 1)[0].decode(enc, "replace")
    return out


def _read_old(buf):
    r = _R(buf)
    rel = r.u("B")
    if rel not in (113, 114, 115):
        raise ValueError(f"dta: unsupported release {rel}")
    r.e = ">" if r.u("B") == 1 else "<"
    r.u("B"), r.u("B")
    K = r.u("H")
    N = r.u("I")
    enc = "latin-1"
    label = r.cstr(81, enc)
    timestamp = r.cstr(18, enc)
    codes = list(r.take(K))
    types = [OLD_TYPES[c] if c in OLD_TYPES else f"str{c}" for c in codes]
    names = [r.cstr(33, enc) for _ in range(K)]
    sortlist = [r.u("H") for _ in range(K + 1)]
    fmts = [r.cstr(12 if rel == 113 else 49, enc) for _ in range(K)]
    vlnames = [r.cstr(33, enc) for _ in range(K)]
    vlabels = [r.cstr(81, enc) for _ in range(K)]
    chars = {}
    while True:
        t = r.u("B")
        ln = r.u("I")
        if t == 0 and ln == 0:
            break
        body = r.take(ln)
        vn = body[:33].split(b"\0", 1)[0].decode(enc, "replace")
        cn = body[33:66].split(b"\0", 1)[0].decode(enc, "replace")
        chars.setdefault(vn, {})[cn] = body[66:].split(b"\0", 1)[0].decode(enc, "replace")
    widths = [int(t[3:]) if t.startswith("str") else SIZE[t] for t in types]
    rowlen = sum(widths)
    data = np.frombuffer(buf, dtype=np.uint8, count=N * rowlen, offset=r.p).reshape(N, rowlen) if N else np.zeros((0, rowlen), np.uint8)
    r.p += N * rowlen
    vlabs = {}
    while r.p + 4 <= len(buf):
        r.u("I")
        lname = r.cstr(33, enc)
        r.take(3)
        vlabs[lname] = _read_vltable(r, enc)
    cols = []
    off = 0
    for i, t in enumerate(types):
        w = widths[i]
        block = data[:, off:off + w]
        off += w
        if t.startswith("str"):
            arr = np.array([bytes(x).split(b"\0", 1)[0].decode(enc, "replace") for x in block], dtype=object)
        else:
            raw = np.ascontiguousarray(block).view(r.e + NP[t]).reshape(N)
            arr = _to_internal(raw.astype("=" + NP[t]), t)
        cols.append(Variable(names[i], t, arr, fmts[i], vlabels[i], vlnames[i]))
    ds = Dataset(cols, label=label, value_labels=vlabs, chars=chars)
    ds.timestamp = timestamp
    ds.sortedby = [names[j - 1] for j in itertools.takewhile(bool, sortlist)]
    return ds


# --- writer (format 118) ---------------------------------------------------

def _from_internal(arr, typ):
    a = np.asarray(arr, dtype=np.float64)
    miss = a >= M.SYSMISS
    if typ in INT_MISS:
        out = np.where(miss, 0, a).astype(np.int64)
        if miss.any():
            idx = np.nonzero(miss)[0]
            for i in idx:
                lab = M.missing_label(a[i])
                out[i] = INT_MISS[typ] + (0 if lab == "." else ord(lab[1]) - 96)
        return out.astype("<" + NP[typ])
    if typ == "float":
        out = np.where(miss, 0, a).astype("<f4")
        if miss.any():
            bits = out.view(np.uint32)
            for i in np.nonzero(miss)[0]:
                lab = M.missing_label(a[i])
                bits[i] = 0x7F000000 + (0 if lab == "." else (ord(lab[1]) - 96) << 11)
        return out
    return a.astype("<f8")


def write_dta(ds, path):
    K = len(ds.vars)
    N = ds.N
    out = bytearray()
    w = out.extend
    w(b"<stata_dta><header><release>118</release><byteorder>LSF</byteorder><K>")
    w(struct.pack("<H", K))
    w(b"</K><N>")
    w(struct.pack("<Q", N))
    w(b"</N><label>")
    lab = (ds.label or "").encode("utf-8")[:320]
    w(struct.pack("<H", len(lab)) + lab)
    w(b"</label><timestamp>")
    timestamp = time.strftime("%d %b %Y %H:%M")
    ts = timestamp.encode()
    w(struct.pack("<B", len(ts)) + ts)
    w(b"</timestamp></header>")
    map_pos = len(out)
    w(b"<map>" + b"\0" * 112 + b"</map>")
    offsets = {}

    def mark(name):
        offsets[name] = len(out)

    mark("variable_types")
    w(b"<variable_types>")
    for v in ds.vars:
        if v.type.startswith("str") and v.type != "strL":
            code = int(v.type[3:])
        else:
            code = {val: key for key, val in NEW_TYPES.items()}[v.type]
        w(struct.pack("<H", code))
    w(b"</variable_types>")

    def fixed(s, n):
        b = (s or "").encode("utf-8")[:n - 1]
        return b + b"\0" * (n - len(b))

    mark("varnames")
    w(b"<varnames>" + b"".join(fixed(v.name, 129) for v in ds.vars) + b"</varnames>")
    mark("sortlist")
    sl = [ds.varindex(n) + 1 for n in (ds.sortedby or []) if ds.has(n)]
    w(b"<sortlist>" + b"".join(struct.pack("<H", x) for x in sl + [0] * (K + 1 - len(sl))) + b"</sortlist>")
    mark("formats")
    w(b"<formats>" + b"".join(fixed(v.format, 57) for v in ds.vars) + b"</formats>")
    mark("value_label_names")
    w(b"<value_label_names>" + b"".join(fixed(v.vlabel, 129) for v in ds.vars) + b"</value_label_names>")
    mark("variable_labels")
    w(b"<variable_labels>" + b"".join(fixed(v.label, 321) for v in ds.vars) + b"</variable_labels>")
    mark("characteristics")
    w(b"<characteristics>")
    for vn, d in (ds.chars or {}).items():
        for cn, txt in d.items():
            body = fixed(vn, 129) + fixed(cn, 129) + txt.encode("utf-8") + b"\0"
            w(b"<ch>" + struct.pack("<I", len(body)) + body + b"</ch>")
    w(b"</characteristics>")
    mark("data")
    w(b"<data>")
    cols = []
    strls = []
    for j, v in enumerate(ds.vars):
        if v.type == "strL":
            enc = []
            for i, s in enumerate(v.data):
                if s == "":
                    enc.append(b"\0" * 8)
                else:
                    vv, oo = j + 1, i + 1
                    strls.append((vv, oo, s.encode("utf-8")))
                    enc.append(struct.pack("<H", vv) + oo.to_bytes(6, "little"))
            cols.append(np.frombuffer(b"".join(enc), dtype=np.uint8).reshape(N, 8) if N else np.zeros((0, 8), np.uint8))
        elif v.type.startswith("str"):
            n = int(v.type[3:])
            cols.append(np.frombuffer(b"".join(fixed2(s, n) for s in v.data), dtype=np.uint8).reshape(N, n) if N else np.zeros((0, n), np.uint8))
        else:
            raw = _from_internal(v.data, v.type)
            cols.append(raw.view(np.uint8).reshape(N, SIZE[v.type]) if N else np.zeros((0, SIZE[v.type]), np.uint8))
    if K and N:
        w(np.hstack(cols).tobytes())
    w(b"</data>")
    mark("strls")
    w(b"<strls>")
    for vv, oo, s in strls:
        w(b"GSO" + struct.pack("<IQBI", vv, oo, 130, len(s) + 1) + s + b"\0")
    w(b"</strls>")
    mark("value_labels")
    w(b"<value_labels>")
    for name, table in (ds.value_labels or {}).items():
        items = sorted(table.items())
        txt = b""
        offs = []
        for _, t in items:
            offs.append(len(txt))
            txt += t.encode("utf-8") + b"\0"
        body = struct.pack("<II", len(items), len(txt)) + b"".join(struct.pack("<I", o) for o in offs)
        body += b"".join(struct.pack("<i", int(k)) for k, _ in items) + txt
        w(b"<lbl>" + struct.pack("<I", len(body)) + fixed(name, 129) + b"\0\0\0" + body + b"</lbl>")
    w(b"</value_labels>")
    mark("stata_data_close")
    w(b"</stata_dta>")
    mark("eof")
    order = ["stata_data", "map", "variable_types", "varnames", "sortlist", "formats", "value_label_names",
             "variable_labels", "characteristics", "data", "strls", "value_labels", "stata_data_close", "eof"]
    offsets["stata_data"] = 0
    offsets["map"] = map_pos
    out[map_pos + 5:map_pos + 5 + 112] = b"".join(struct.pack("<Q", offsets[k]) for k in order)
    with open(path, "wb") as f:
        f.write(out)
    return timestamp


def fixed2(s, n):
    b = (s or "").encode("utf-8")[:n]
    return b + b"\0" * (n - len(b))
