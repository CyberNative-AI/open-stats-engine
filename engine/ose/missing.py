"""Numeric missing values.

In memory every numeric column is float64. Missing values use the same bit
patterns the .dta format uses for doubles: system missing "." is 2**1023 and
the extended missing values .a-.z follow it in steps of 2**(1023-12). They are
finite and larger than every valid number, so ordinary comparisons already
order them the way the language does (missing sorts above all numbers).
"""
import struct

import numpy as np


def _d(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


SYSMISS = _d(0x7FE0000000000000)
EXT = {chr(ord("a") + i): _d(0x7FE0000000000000 + (i + 1) * 0x0000010000000000) for i in range(26)}
CODE_OF = {SYSMISS: "."}
CODE_OF.update({v: "." + k for k, v in EXT.items()})
# Largest valid double the language allows; anything >= SYSMISS is missing.
MAXDOUBLE = _d(0x7FDFFFFFFFFFFFFF)


def is_missing(x):
    return np.asarray(x) >= SYSMISS


def clean(a):
    """Map NaN, inf and out-of-range results to system missing."""
    a = np.asarray(a, dtype=np.float64)
    bad = ~np.isfinite(a) | (np.abs(a) > MAXDOUBLE)
    if bad.any():
        a = a.copy()
        a[bad] = SYSMISS
    return a


def missing_label(x):
    return CODE_OF.get(float(x), ".")
