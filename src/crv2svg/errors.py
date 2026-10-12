class CrvError(Exception):
    """The file could not be read as a CRV project."""


class UnsupportedError(CrvError):
    """The file is a CRV project but uses a record this reader does not know."""

    def __init__(self, message, partial=None):
        super().__init__(message)
        self.partial = partial
