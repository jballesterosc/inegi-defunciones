"""A small, fast reader for the (simple) DBF files INEGI ships.

INEGI's EDR microdata uses only character ('C') and numeric ('N') fields with
no memo/BLOB side files, so we can map the fixed-width record layout straight
onto a NumPy structured dtype and slice whole columns at once — far faster than
row-by-row iteration for the ~1M-row yearly tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

TERMINATOR = 0x0D
DELETED = ord("*")

# dBASE "language driver" byte (offset 29) -> Python codec. Only the values that
# turn up in INEGI files plus the common ones; unknown/0x00 -> caller's default.
LANGUAGE_DRIVER_CODECS = {
    0x01: "cp437",
    0x02: "cp850",
    0x03: "cp1252",
    0x08: "cp865",
    0x0A: "cp850",
    0x0E: "cp850",
    0x10: "cp850",
    0x57: "cp1252",
    0x58: "cp1252",
    0x59: "cp1252",
    0x64: "cp852",
    0xC8: "cp1250",
    0xC9: "cp1251",
}


def encoding_for(language_driver: int, default: str = "cp850") -> str:
    return LANGUAGE_DRIVER_CODECS.get(language_driver, default)


@dataclass(frozen=True)
class DbfField:
    name: str
    type: str
    length: int
    decimals: int


@dataclass(frozen=True)
class DbfHeader:
    n_records: int
    header_len: int
    record_len: int
    fields: tuple[DbfField, ...]
    language_driver: int


def read_header(data: bytes | memoryview) -> DbfHeader:
    if len(data) < 32:
        raise ValueError("file too short to be a DBF")
    n_records = int.from_bytes(data[4:8], "little")
    header_len = int.from_bytes(data[8:10], "little")
    record_len = int.from_bytes(data[10:12], "little")
    language_driver = data[29]

    fields: list[DbfField] = []
    pos = 32
    while pos + 1 < len(data) and pos < header_len and data[pos] != TERMINATOR:
        raw = data[pos : pos + 32]
        if len(raw) < 32:
            break
        name = raw[:11].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
        ftype = chr(raw[11])
        flen = raw[16]
        fdec = raw[17]
        fields.append(DbfField(name=name or f"F{len(fields)}", type=ftype,
                               length=flen, decimals=fdec))
        pos += 32

    return DbfHeader(
        n_records=n_records,
        header_len=header_len,
        record_len=record_len,
        fields=tuple(fields),
        language_driver=language_driver,
    )


def _unique_names(fields: tuple[DbfField, ...]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for f in fields:
        if f.name in seen:
            seen[f.name] += 1
            out.append(f"{f.name}_{seen[f.name]}")
        else:
            seen[f.name] = 0
            out.append(f.name)
    return out


@dataclass
class DbfTable:
    header: DbfHeader
    names: list[str]  # de-duplicated, positional match with header.fields
    records: np.ndarray  # structured array, one void field per column ("S<len>")

    def __len__(self) -> int:
        return len(self.records)

    def is_ascii(self) -> bool:
        """True when no byte in the record body has the high bit set."""
        if not self.records.size:
            return True
        flat = np.frombuffer(self.records.tobytes(), dtype=np.uint8)
        return bool(flat.max() < 0x80)


def read_table(path: Path) -> DbfTable:
    """Load a DBF into a structured NumPy array of raw byte columns (no decoding)."""
    path = Path(path)
    data = path.read_bytes()
    header = read_header(data)

    names = _unique_names(header.fields)
    np_dtype = np.dtype(
        [("_deleted", "S1")]
        + [(nm, f"S{max(f.length, 1)}") for nm, f in zip(names, header.fields, strict=True)]
    )
    if np_dtype.itemsize != header.record_len:
        # Trust the header's record length; pad/trim the trailing field's slot.
        np_dtype = _fit_record_len(names, header, header.record_len)

    avail = (len(data) - header.header_len) // header.record_len
    n = min(header.n_records, avail) if header.n_records else avail
    body = np.frombuffer(data, dtype=np_dtype, count=n, offset=header.header_len)
    if body.size:
        body = body[body["_deleted"] != bytes([DELETED])]
    return DbfTable(header=header, names=names, records=body)


def _fit_record_len(names: list[str], header: DbfHeader, record_len: int) -> np.dtype:
    fields = list(header.fields)
    specs = [("_deleted", "S1")]
    used = 1
    for i, (nm, f) in enumerate(zip(names, fields, strict=True)):
        if i == len(fields) - 1:
            width = max(record_len - used, 1)
        else:
            width = max(f.length, 1)
        specs.append((nm, f"S{width}"))
        used += width
    if used < record_len:
        specs.append(("_pad", f"S{record_len - used}"))
    return np.dtype(specs)
