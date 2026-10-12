"""Reader for the MFC CArchive object stream the vector data is written in."""

import struct

from .errors import CrvError, UnsupportedError

NEW_CLASS = 0xFFFF
BIG_TAG = 0x7FFF
CLASS_BIT = 0x8000
BIG_CLASS_BIT = 0x80000000


class Archive:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        # Slot 0 is the null object; classes and objects share one index space.
        self.table = [None]
        self.warnings = []

    def _take(self, fmt, size):
        if self.pos + size > len(self.data):
            raise CrvError("vector data ends in the middle of a record")
        value, = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return value

    def u8(self):
        return self._take("<B", 1)

    def u16(self):
        return self._take("<H", 2)

    def u32(self):
        return self._take("<I", 4)

    def i32(self):
        return self._take("<i", 4)

    def f64(self):
        return self._take("<d", 8)

    def raw(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise CrvError("vector data ends in the middle of a record")
        out = self.data[self.pos:self.pos + size]
        self.pos += size
        return out

    def expect_u32(self, allowed, what):
        value = self.u32()
        if value not in allowed:
            raise UnsupportedError(
                "%s has version %d, this reader knows %s (offset %d)"
                % (what, value, "/".join(str(a) for a in allowed), self.pos - 4))
        return value

    def count(self, what, each=1):
        """Read a u32 element count and refuse one the remaining bytes cannot hold."""
        n = self.u32()
        if n * each > len(self.data) - self.pos:
            raise CrvError("%s count %d does not fit in the file" % (what, n))
        return n

    def string(self):
        n = self.u8()
        wide = False
        if n == 0xFF:
            n = self.u16()
            if n == 0xFFFE:
                wide = True
                n = self.u8()
                if n == 0xFF:
                    n = self.u16()
                    if n == 0xFFFF:
                        n = self.u32()
            elif n == 0xFFFF:
                n = self.u32()
        if wide:
            return self.raw(n * 2).decode("utf-16-le", "replace")
        return self.raw(n).decode("cp1252", "replace")

    def object_header(self):
        """Read an object tag. Returns None for null, else the class name."""
        tag = self.u16()
        if tag == NEW_CLASS:
            self.u16()
            name = self.raw(self.u16()).decode("ascii", "replace")
            self.table.append(("class", name))
        else:
            if tag == BIG_TAG:
                ref = self.u32()
                is_class, index = bool(ref & BIG_CLASS_BIT), ref & ~BIG_CLASS_BIT
            else:
                is_class, index = bool(tag & CLASS_BIT), tag & ~CLASS_BIT
            if not is_class:
                if index == 0:
                    return None
                raise UnsupportedError("shared object reference at offset %d" % self.pos)
            if index >= len(self.table) or self.table[index] is None or self.table[index][0] != "class":
                raise CrvError("object refers to a class that was never defined (offset %d)" % self.pos)
            name = self.table[index][1]
        self.table.append(("object", name))
        return name
