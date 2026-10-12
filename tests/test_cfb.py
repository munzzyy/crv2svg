import struct

import pytest

from crv2svg import cfb
from crv2svg.errors import CrvError
from crvbuild import build_cfb


def test_round_trip_small_and_large_streams():
    streams = {
        "A/tiny": b"x",
        "A/empty": b"",
        "A/mini": bytes(range(256)) * 3,
        "B/edge": b"e" * 4096,
        "B/large": bytes(i % 251 for i in range(70000)),
    }
    assert cfb.read_streams(build_cfb(streams)) == streams


def test_rejects_other_files():
    with pytest.raises(CrvError):
        cfb.read_streams(b"<svg></svg>" * 100)
    with pytest.raises(CrvError):
        cfb.read_streams(b"")


def test_truncated_container_is_an_error_not_a_crash():
    data = build_cfb({"A/large": b"z" * 20000, "A/mini": b"m" * 100})
    for cut in range(0, len(data), 97):
        try:
            cfb.read_streams(data[:cut])
        except CrvError:
            pass


def test_looping_sector_chain_terminates():
    data = bytearray(build_cfb({"A/large": b"z" * 20000}))
    fat_at = 512
    entries = list(struct.unpack_from("<128I", data, fat_at))
    first_data = next(i for i, v in enumerate(entries) if v not in (0xFFFFFFFD,))
    entries[first_data] = first_data
    struct.pack_into("<128I", data, fat_at, *entries)
    with pytest.raises(CrvError):
        cfb.read_streams(bytes(data))


def test_stream_size_larger_than_file_is_refused():
    data = bytearray(build_cfb({"A/large": b"z" * 20000}))
    at = data.find("large".encode("utf-16-le"))
    struct.pack_into("<Q", data, at + 120, 1 << 40)
    with pytest.raises(CrvError):
        cfb.read_streams(bytes(data))
