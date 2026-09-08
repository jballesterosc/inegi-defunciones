"""Unzip downloaded archives and locate the DBF tables inside them.

Individual-year archives (2020+) hold a flat set of files. The multi-year
bundles nest one folder per year:

    defunciones_base_datos_2015/DEFUN15.DBF
    defunciones_base_datos_2015/CAPGPO.dbf
    defunciones_base_datos_2016/DEFUN16.dbf
    ...

so we keep the archive's internal directory layout and group files into one
:class:`YearUnit` per year.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Main record-level table: DEFUN23.DBF (2-digit year) or DEFUN2005.DBF.
_MAIN_RE = re.compile(r"^defun[a-z_]*?(\d{2,4})\.dbf$", re.IGNORECASE)


@dataclass
class YearUnit:
    year: int
    directory: Path
    main_dbf: Path
    catalogs: dict[str, Path] = field(default_factory=dict)  # UPPER stem -> path
    extras: list[Path] = field(default_factory=list)  # PDFs, notes, ...


@dataclass
class ExtractedArchive:
    key: str
    root: Path
    units: list[YearUnit]

    @property
    def years(self) -> list[int]:
        return sorted(u.year for u in self.units)

    def unit(self, year: int) -> YearUnit | None:
        for u in self.units:
            if u.year == year:
                return u
        return None


def _year_from_main(name: str) -> int | None:
    m = _MAIN_RE.match(Path(name).name)
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 4:
        return int(digits)
    yy = int(digits)
    return 1900 + yy if yy >= 90 else 2000 + yy  # EDR starts in 1990


def _safe_extract(zf: zipfile.ZipFile, root: Path) -> None:
    root = root.resolve()
    for member in zf.infolist():
        if member.is_dir():
            continue
        target = (root / member.filename).resolve()
        if not str(target).startswith(str(root) + "/") and target != root:
            raise RuntimeError(f"unsafe path in zip: {member.filename!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)


def extract_archive(zip_path: Path, dest_root: Path, *, force: bool = False) -> ExtractedArchive:
    """Extract ``zip_path`` under ``dest_root`` and group its DBFs by year."""
    zip_path = Path(zip_path)
    key = zip_path.name
    for suffix in ("_dbf.zip", ".zip"):
        if key.lower().endswith(suffix):
            key = key[: -len(suffix)]
            break
    root = dest_root / key
    marker = root / ".extracted"

    if not (marker.exists() and not force):
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, root)
        marker.write_text("ok\n")

    # Find every main table, then attach sibling files from the same directory.
    units: list[YearUnit] = []
    for dbf in sorted(root.rglob("*")):
        if dbf.suffix.lower() != ".dbf":
            continue
        year = _year_from_main(dbf.name)
        if year is None:
            continue
        unit = YearUnit(year=year, directory=dbf.parent, main_dbf=dbf)
        for sib in sorted(dbf.parent.iterdir()):
            if sib == dbf or sib.name == ".extracted":
                continue
            if sib.suffix.lower() == ".dbf":
                unit.catalogs[sib.stem.upper()] = sib
            elif sib.is_file():
                unit.extras.append(sib)
        units.append(unit)

    if not units:
        raise RuntimeError(f"No DEFUN*.dbf table found in {zip_path}")
    units.sort(key=lambda u: u.year)
    return ExtractedArchive(key=key, root=root, units=units)
