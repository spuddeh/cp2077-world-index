"""The game's .archive files and CR2W files read with no WolvenKit code: the game's own Oodle DLL, and layouts only.

Used by raw_check.py and world_check.py.
"""
import ctypes
import glob
import os
import struct

_oodle = None


def load_oodle(game_dir):
    global _oodle
    _oodle = ctypes.WinDLL(game_dir + "/bin/x64/oo2ext_7_win64.dll")
    _oodle.OodleLZ_Decompress.restype = ctypes.c_longlong
    _oodle.OodleLZ_Decompress.argtypes = [ctypes.c_char_p, ctypes.c_longlong, ctypes.c_char_p, ctypes.c_longlong] + [ctypes.c_longlong] * 10


def kraken(data):
    assert data[:4] == b"KARK", data[:8]
    size = struct.unpack_from("<I", data, 4)[0]
    out = ctypes.create_string_buffer(size)
    got = _oodle.OodleLZ_Decompress(data[8:], len(data) - 8, out, size, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3)
    assert got == size, (got, size)
    return out.raw


def fnv(text):
    h = 0xcbf29ce484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xffffffffffffffff
    return h


class Archive:
    def __init__(self, path):
        self.f = open(path, "rb")
        magic, _version, index_pos, _index_size = struct.unpack("<IIQI", self.f.read(20))
        assert magic == 0x52414452, hex(magic)
        self.f.seek(index_pos)
        _table_offset, _table_size, _crc, entries, segments, _deps = struct.unpack("<IIQIII", self.f.read(28))
        self.entries = {}
        data = self.f.read(entries * 56)
        for k in range(entries):
            h, _ts, _inline, start, end = struct.unpack_from("<QqIII", data, k * 56)
            self.entries[h] = (start, end)
        self.segments = list(struct.iter_unpack("<QII", self.f.read(segments * 16)))

    def read(self, h):
        start, end = self.entries[h]
        parts = []
        for k in range(start, end):
            offset, zsize, size = self.segments[k]
            self.f.seek(offset)
            raw = self.f.read(zsize)
            parts.append(kraken(raw) if k == start and zsize != size else raw)
        return b"".join(parts)


def game_files(game_dir, edition):
    """path hash -> the archive whose copy the game loads: the base game's, then Phantom Liberty's over it for ep1."""
    winner = {}
    for folder in ("content", "ep1") if edition == "ep1" else ("content",):
        for path in sorted(glob.glob(f"{game_dir}/archive/pc/{folder}/*.archive")):
            name = os.path.basename(path)
            if name.startswith("lang_") or name.startswith("audio_"):
                continue
            a = Archive(path)
            for h in a.entries:
                winner[h] = a
    return winner
