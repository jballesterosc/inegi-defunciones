"""Tests for the minimal DBF reader against a hand-built dBASE III file."""

from __future__ import annotations

import struct

from inegi_defunciones.dbf import encoding_for, read_header, read_table


def _make_dbf(fields, rows, *, language_driver=0x03):
    """Build a tiny dBASE III+ file. ``fields`` = list of (name, type, len, dec)."""
    header = bytearray(32)
    header[0] = 0x03
    header[29] = language_driver
    field_defs = b""
    for name, ftype, flen, dec in fields:
        fd = bytearray(32)
        fd[0:11] = name.encode("ascii").ljust(11, b"\x00")[:11]
        fd[11] = ord(ftype)
        fd[16] = flen
        fd[17] = dec
        field_defs += bytes(fd)
    field_defs += b"\x0d"

    record_len = 1 + sum(f[2] for f in fields)
    header_len = 32 + len(field_defs)
    struct.pack_into("<I", header, 4, len(rows))
    struct.pack_into("<H", header, 8, header_len)
    struct.pack_into("<H", header, 10, record_len)

    body = b""
    for row in rows:
        body += b" "  # not deleted
        for (_name, ftype, flen, _dec), value in zip(fields, row, strict=True):
            body += (
                str(value).encode("latin-1").ljust(flen)[:flen]
                if ftype == "C"
                else str(value).encode("ascii").rjust(flen)[:flen]
            )
    body += b"\x1a"
    return bytes(header) + field_defs + body


FIELDS = [("ENT", "C", 2, 0), ("EDAD", "N", 4, 0), ("PESO", "N", 6, 2)]


def test_read_header(tmp_path):
    p = tmp_path / "t.dbf"
    p.write_bytes(_make_dbf(FIELDS, [("01", 45, "70.50")]))
    h = read_header(p.read_bytes())
    assert h.n_records == 1
    assert [f.name for f in h.fields] == ["ENT", "EDAD", "PESO"]
    assert h.fields[1].type == "N" and h.fields[1].decimals == 0
    assert h.fields[2].decimals == 2


def test_read_table_values(tmp_path):
    p = tmp_path / "t.dbf"
    p.write_bytes(_make_dbf(FIELDS, [("01", 45, "70.50"), ("09", 3, "12.00")]))
    tbl = read_table(p)
    assert len(tbl) == 2
    assert tbl.records["ENT"].tolist() == [b"01", b"09"]
    assert tbl.records["EDAD"].tolist() == [b"  45", b"   3"]


def test_deleted_rows_are_dropped(tmp_path):
    raw = bytearray(_make_dbf(FIELDS, [("01", 1, "0"), ("02", 2, "0"), ("03", 3, "0")]))
    header_len = raw[8] | (raw[9] << 8)
    record_len = raw[10] | (raw[11] << 8)
    raw[header_len + record_len] = ord("*")  # mark 2nd record deleted
    p = tmp_path / "t.dbf"
    p.write_bytes(bytes(raw))
    tbl = read_table(p)
    assert tbl.records["ENT"].tolist() == [b"01", b"03"]


def test_truncated_record_count_is_clamped(tmp_path):
    good = _make_dbf(FIELDS, [("01", 1, "0"), ("02", 2, "0")])
    # claim 5 records in the header but only ship 2
    raw = bytearray(good)
    struct.pack_into("<I", raw, 4, 5)
    p = tmp_path / "t.dbf"
    p.write_bytes(bytes(raw))
    assert len(read_table(p)) == 2


def test_encoding_for():
    assert encoding_for(0x02) == "cp850"
    assert encoding_for(0x03) == "cp1252"
    assert encoding_for(0x00, default="latin-1") == "latin-1"


def test_is_ascii(tmp_path):
    p = tmp_path / "t.dbf"
    p.write_bytes(_make_dbf([("N", "C", 6, 0)], [("PEREZ",), ("LOPEZ",)]))
    assert read_table(p).is_ascii()

    p2 = tmp_path / "t2.dbf"
    rows = [("NOEL",), ("PE\xd1A",)]  # Ñ in latin-1/cp850 range
    p2.write_bytes(_make_dbf([("N", "C", 6, 0)], rows))
    assert not read_table(p2).is_ascii()
