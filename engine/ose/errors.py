class StataError(Exception):
    """A user-facing error with a return code, printed as the language does."""

    def __init__(self, msg, rc=198):
        super().__init__(msg)
        self.msg = msg
        self.rc = rc


class Unsupported(StataError):
    """Raised for anything the engine does not implement. Never guess."""

    def __init__(self, what):
        super().__init__(f"ose: not implemented: {what}", 199)
        self.what = what
        self.cmd = None  # command name, set by dispatch; used for the transcript's last line


class ExitDo(Exception):
    """`exit` inside a do-file."""
