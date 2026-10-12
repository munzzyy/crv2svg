"""Minimal reader for the compound file container (MS-CFB) a CRV project lives in."""

import struct

from .errors import CrvError

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
END_OF_CHAIN = 0xFFFFFFFE
NO_STREAM = 0xFFFFFFFF
MAX_STREAM = 512 * 1024 * 1024
MAX_ENTRIES = 4096


def read_streams(data):
    """Return {"Storage/Stream": bytes} for every stream in the container."""
    if len(data) < 512 or data[:8] != MAGIC:
        raise CrvError("not a compound file, so not a CRV project")
    try:
        return _read(data)
    except (struct.error, IndexError) as exc:
        raise CrvError("compound file is truncated or corrupt") from exc


def _read(data):
    sector_shift, mini_shift = struct.unpack_from("<HH", data, 30)
    if sector_shift not in (9, 12) or mini_shift != 6:
        raise CrvError("compound file has an unsupported sector size")
    ssz, msz = 1 << sector_shift, 1 << mini_shift
    dir_start, = struct.unpack_from("<I", data, 48)
    cutoff, mini_start = struct.unpack_from("<II", data, 56)
    difat_start, difat_count = struct.unpack_from("<II", data, 68)
    total_sectors = max(len(data) // ssz - 1, 0)
    per_sector = ssz // 4

    def sector(n):
        if n >= total_sectors:
            raise CrvError("compound file points past its own end")
        off = (n + 1) * ssz
        return data[off:off + ssz]

    difat = [x for x in struct.unpack_from("<109I", data, 76) if x < END_OF_CHAIN]
    nxt, hops = difat_start, 0
    while nxt < END_OF_CHAIN:
        hops += 1
        if hops > difat_count + 1 or hops > total_sectors:
            raise CrvError("compound file has a looping allocation table")
        vals = struct.unpack("<%dI" % per_sector, sector(nxt))
        difat += [x for x in vals[:-1] if x < END_OF_CHAIN]
        nxt = vals[-1]
    if len(difat) > total_sectors:
        raise CrvError("compound file allocation table is larger than the file")
    fat = []
    for s in difat:
        fat += struct.unpack("<%dI" % per_sector, sector(s))

    def chain(start, table):
        out, n = [], start
        while n < END_OF_CHAIN:
            if n >= len(table) or len(out) > len(table):
                raise CrvError("compound file has a broken sector chain")
            out.append(n)
            n = table[n]
        return out

    def big(start, size=None):
        sectors = chain(start, fat)
        if size is not None:
            sectors = sectors[:(size + ssz - 1) // ssz]
        blob = b"".join(sector(n) for n in sectors)
        return blob if size is None else blob[:size]

    dirdata = big(dir_start)
    entries = []
    for i in range(0, min(len(dirdata), MAX_ENTRIES * 128) - 127, 128):
        e = dirdata[i:i + 128]
        name_len, = struct.unpack_from("<H", e, 64)
        name = e[:max(min(name_len, 64) - 2, 0)].decode("utf-16-le", "replace")
        left, right, child = struct.unpack_from("<III", e, 68)
        start, = struct.unpack_from("<I", e, 116)
        size, = struct.unpack_from("<Q", e, 120)
        entries.append((name, e[66], left, right, child, start, size))
    if not entries or entries[0][1] != 5:
        raise CrvError("compound file has no root entry")

    root = entries[0]
    ministream = big(root[5], root[6]) if root[5] < END_OF_CHAIN else b""
    minifat = []
    if mini_start < END_OF_CHAIN:
        raw = big(mini_start)
        minifat = struct.unpack("<%dI" % (len(raw) // 4), raw)

    def stream(entry):
        start, size = entry[5], entry[6]
        if size > MAX_STREAM or size > len(data):
            raise CrvError("compound file stream is larger than the file")
        if size == 0:
            return b""
        if size < cutoff:
            parts = [ministream[n * msz:(n + 1) * msz] for n in chain(start, minifat)]
            return b"".join(parts)[:size]
        return big(start, size)

    out, seen, budget = {}, set(), len(data)
    todo = [(root[4], "")]
    while todo:
        idx, prefix = todo.pop()
        if idx == NO_STREAM or idx >= len(entries) or idx in seen:
            continue
        seen.add(idx)
        name, kind, left, right, child, _, _ = entries[idx]
        todo.append((left, prefix))
        todo.append((right, prefix))
        if kind == 2:
            # Streams cannot overlap, so together they never outweigh the file.
            budget -= entries[idx][6]
            if budget < 0:
                raise CrvError("compound file streams add up to more than the file")
            out[prefix + name] = stream(entries[idx])
        elif kind == 1:
            todo.append((child, prefix + name + "/"))
    return out
