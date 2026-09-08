"""Convert INEGI DBF tables to Parquet and/or CSV.

Uses the fast column-wise reader in :mod:`inegi_defunciones.dbf`, then maps each
DBF field to an Arrow type:

* ``C``                     -> string (blank -> null)
* ``N``/``F`` no decimals   -> int64  (falls back to float64, then string)
* ``N``/``F`` with decimals -> float64 (falls back to string)
* ``D``                     -> date32 (falls back to string)
* ``L``                     -> bool
* anything else / ``M``     -> string

Text is decoded as ASCII where possible (the bulk of the microdata is numeric
codes); files with high-bit bytes are decoded with the codec named by their
dBASE language-driver byte (cp850 for INEGI's DOS-era catalog tables, cp1252
for the Windows-era ones), falling back to :data:`DEFAULT_ENCODING`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from .dbf import DbfField, encoding_for, read_table

#: fallback when a DBF's language-driver byte is 0x00 (unknown). INEGI's catalog
#: tables are overwhelmingly DOS cp850; the main table is pure ASCII.
DEFAULT_ENCODING = "cp850"
_NULL_STR = pa.scalar(None, pa.string())


@dataclass(frozen=True)
class ConvertResult:
    source: Path
    rows: int
    outputs: list[Path]


def _column_is_ascii(col: np.ndarray) -> bool:
    if not col.size:
        return True
    flat = np.frombuffer(np.ascontiguousarray(col).tobytes(), dtype=np.uint8)
    return bool(flat.max() < 0x80)


def _string_column(col: np.ndarray, encoding: str, *, ascii_ok: bool) -> pa.Array:
    if ascii_ok or _column_is_ascii(col):
        # pure ASCII: reinterpret the bytes as UTF-8 directly (fast)
        s = pc.cast(pa.array(col), pa.string())
    else:
        s = pa.array(np.char.decode(col, encoding, "replace"), type=pa.string())
    s = pc.utf8_trim_whitespace(s)
    return pc.if_else(pc.equal(s, ""), _NULL_STR, s)


def _to_arrow(field: DbfField, col: np.ndarray, encoding: str, *, ascii_ok: bool) -> pa.Array:
    ftype = field.type.upper()
    s = _string_column(col, encoding, ascii_ok=ascii_ok)

    if ftype in ("N", "F", "B"):
        targets = (pa.int64(), pa.float64()) if field.decimals == 0 else (pa.float64(),)
        for target in targets:
            try:
                return pc.cast(s, target)
            except pa.lib.ArrowInvalid:
                continue
        return s

    if ftype == "L":
        up = pc.utf8_upper(s)
        return pc.if_else(
            pc.is_in(up, value_set=pa.array(["T", "Y"])),
            True,
            pc.if_else(pc.is_in(up, value_set=pa.array(["F", "N"])), False, None),
        ).cast(pa.bool_())

    if ftype == "D":
        try:
            ts = pc.strptime(s, format="%Y%m%d", unit="s", error_is_null=True)
            return pc.cast(ts, pa.date32())
        except (pa.lib.ArrowInvalid, pa.lib.ArrowNotImplementedError):
            return s

    return s


def dbf_to_table(path: Path, *, encoding: str | None = None) -> pa.Table:
    """Read a DBF into an Arrow table.

    ``encoding`` overrides the codec for every column; by default it is taken
    from each file's language-driver byte, falling back to :data:`DEFAULT_ENCODING`.
    """
    tbl = read_table(Path(path))
    enc = encoding or encoding_for(tbl.header.language_driver, DEFAULT_ENCODING)
    ascii_ok = tbl.is_ascii()
    arrays, names = [], []
    for name, field in zip(tbl.names, tbl.header.fields, strict=True):
        if field.type.upper() == "M":  # memo -> needs a side file we don't have
            continue
        arrays.append(_to_arrow(field, tbl.records[name], enc, ascii_ok=ascii_ok))
        names.append(name)
    return pa.Table.from_arrays(arrays, names=names)


def _atomic_write(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def convert_dbf(
    dbf_path: Path,
    out_dir: Path,
    *,
    stem: str | None = None,
    formats: Iterable[str] = ("parquet",),
    encoding: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> ConvertResult:
    """Convert one DBF file to the requested ``formats`` ("parquet", "csv")."""
    dbf_path = Path(dbf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or dbf_path.stem.lower()
    formats = list(formats)
    targets = {fmt: out_dir / f"{stem}.{fmt}" for fmt in formats}

    if not force and all(p.exists() for p in targets.values()):
        pf = targets.get("parquet")
        rows = pq.ParquetFile(pf).metadata.num_rows if pf and pf.exists() else -1
        return ConvertResult(dbf_path, rows, list(targets.values()))

    if not quiet:
        print(f"    converting {dbf_path.name} ...", flush=True)
    table = dbf_to_table(dbf_path, encoding=encoding)

    if "parquet" in formats:
        _atomic_write(targets["parquet"], lambda p: pq.write_table(table, p, compression="zstd"))
    if "csv" in formats:
        # pyarrow quotes only fields that need it and writes nulls as empty
        _atomic_write(targets["csv"], lambda p: pacsv.write_csv(table, p))
    return ConvertResult(dbf_path, table.num_rows, list(targets.values()))
