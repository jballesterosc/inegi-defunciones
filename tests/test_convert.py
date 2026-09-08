from __future__ import annotations

import pyarrow.parquet as pq

from inegi_defunciones.convert import convert_dbf, dbf_to_table
from tests.test_dbf import _make_dbf

FIELDS = [("ENT", "C", 2, 0), ("EDAD", "N", 4, 0), ("TASA", "N", 6, 2), ("NOMBRE", "C", 8, 0)]
ROWS = [
    ("01", 45, "70.50", "PEREZ"),
    ("09", 3, "12.00", "LOPEZ"),
    ("  ", "", "", ""),  # blanks -> nulls
]


def test_types_and_nulls(tmp_path):
    p = tmp_path / "t.dbf"
    p.write_bytes(_make_dbf(FIELDS, ROWS))
    t = dbf_to_table(p)
    assert t.schema.field("ENT").type == "string"
    assert t.schema.field("EDAD").type == "int64"
    assert t.schema.field("TASA").type == "double"
    d = t.to_pydict()
    assert d["ENT"] == ["01", "09", None]
    assert d["EDAD"] == [45, 3, None]
    assert d["TASA"] == [70.5, 12.0, None]
    assert d["NOMBRE"] == ["PEREZ", "LOPEZ", None]


def test_leading_zeros_preserved(tmp_path):
    p = tmp_path / "t.dbf"
    p.write_bytes(_make_dbf([("CVE", "C", 4, 0)], [("0007",), ("0106",)]))
    assert dbf_to_table(p).to_pydict()["CVE"] == ["0007", "0106"]


def test_cp850_catalog_text(tmp_path):
    p = tmp_path / "c.dbf"
    # "Cólera": ó is 0xA2 in cp850
    p.write_bytes(_make_dbf([("D", "C", 8, 0)], [("C\xf3lera",)], language_driver=0x02))
    # emulate a cp850-encoded file: re-encode the byte for ó
    raw = bytearray(p.read_bytes())
    raw = raw.replace("Cólera".encode("latin-1").ljust(8), "Cólera".encode("cp850").ljust(8))
    p.write_bytes(bytes(raw))
    assert dbf_to_table(p).to_pydict()["D"] == ["Cólera"]


def test_convert_dbf_writes_both_formats(tmp_path):
    src = tmp_path / "t.dbf"
    src.write_bytes(_make_dbf(FIELDS, ROWS))
    out = tmp_path / "out"
    res = convert_dbf(src, out, stem="year_2020", formats=["parquet", "csv"])
    assert res.rows == 3
    assert (out / "year_2020.parquet").exists()
    assert (out / "year_2020.csv").exists()
    assert pq.ParquetFile(out / "year_2020.parquet").metadata.num_rows == 3

    # idempotent: second call is a no-op that still reports the row count
    res2 = convert_dbf(src, out, stem="year_2020", formats=["parquet", "csv"])
    assert res2.rows == 3
