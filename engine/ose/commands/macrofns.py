"""Extended macro functions (`: ...') and c() values."""
import os
import re
import time

from .. import missing as M
from ..errors import StataError, Unsupported


def extended(it, text):
    m = re.match(r"^word\s+count\s+(.*)$", text, re.S)
    if m:
        from .control import _split_items
        return str(len(_split_items(m.group(1))))
    m = re.match(r"^word\s+(\d+)\s+of\s+(.*)$", text, re.S)
    if m:
        from .control import _split_items
        items = _split_items(m.group(2))
        k = int(m.group(1))
        return items[k - 1] if 1 <= k <= len(items) else ""
    m = re.match(r"^(variable\s+label|var\s+label|var\s+l|variable\s+l)\s+(\S+)$", text)
    if m:
        return it.ds.find(m.group(2)).label
    m = re.match(r"^type\s+(\S+)$", text)
    if m:
        return it.ds.find(m.group(1)).type
    m = re.match(r"^format\s+(\S+)$", text)
    if m:
        return it.ds.find(m.group(1)).format
    m = re.match(r"^value\s+label\s+(\S+)$", text)
    if m:
        return it.ds.find(m.group(1)).vlabel
    m = re.match(r"^list\s+sizeof\s+(\S+)$", text)
    if m:
        return str(len(it.locals.get(m.group(1), "").split()))
    m = re.match(r"^length\s+local\s+(\S+)$", text)
    if m:
        return str(len(it.locals.get(m.group(1), "")))
    raise Unsupported(f"extended macro function : {text.split()[0] if text.split() else ''}")


def cvalue(it, name):
    t = time.localtime()
    vals = {
        "N": float(it.ds.N), "k": float(len(it.ds.vars)), "pwd": it.cwd, "rc": float(it.rc),
        "current_date": time.strftime("%e %b %Y", t).strip(), "current_time": time.strftime("%H:%M:%S", t),
        "pi": 3.141592653589793, "maxdouble": M.MAXDOUBLE, "dirsep": "/", "os": "Unix",
        "level": 95.0, "linesize": 80.0, "more": "off", "varabbrev": it.settings.get("varabbrev", "on"),
        "filename": it.ds.filename, "type": it.settings.get("type", "float"),
        "alpha": "a b c d e f g h i j k l m n o p q r s t u v w x y z",
        "ALPHA": "A B C D E F G H I J K L M N O P Q R S T U V W X Y Z",
        "Mons": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec",
    }
    if name in vals:
        return vals[name]
    raise Unsupported(f"c({name})")
