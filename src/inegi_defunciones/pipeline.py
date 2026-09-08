"""End-to-end orchestration: download -> extract -> convert."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog, refresh_catalog
from .convert import convert_dbf
from .download import download_file, sha256
from .extract import YearUnit, extract_archive

DEFAULT_YEARS = list(range(2005, 2025))  # "last 20 years" as of 2026


@dataclass
class Paths:
    root: Path
    raw: Path = field(init=False)
    interim: Path = field(init=False)
    processed: Path = field(init=False)
    catalogos: Path = field(init=False)

    def __post_init__(self) -> None:
        self.raw = self.root / "raw"
        self.interim = self.root / "interim"
        self.processed = self.root / "processed"
        self.catalogos = self.processed / "catalogos"

    def make(self) -> None:
        for p in (self.raw, self.interim, self.processed, self.catalogos):
            p.mkdir(parents=True, exist_ok=True)


def resolve_years(start: int | None, end: int | None, years: list[int] | None) -> list[int]:
    if years:
        return sorted(set(years))
    if start is None and end is None:
        return list(DEFAULT_YEARS)
    return list(range((start or 1990), (end or 2024) + 1))


def run(
    *,
    data_dir: Path,
    years: list[int],
    formats: list[str],
    catalog: Catalog | None = None,
    use_api_catalog: bool = False,
    download_only: bool = False,
    keep_zip: bool = True,
    force: bool = False,
    quiet: bool = False,
) -> dict:
    paths = Paths(Path(data_dir))
    paths.make()

    if catalog is None:
        catalog = refresh_catalog() if use_api_catalog else Catalog()
    archives = catalog.archives_for_years(years)
    wanted = set(years)

    manifest: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "https://www.inegi.org.mx/programas/edr/#datos_abiertos",
        "years_requested": years,
        "formats": formats,
        "archives": [],
        "tables": [],
    }

    for archive in archives:
        zip_path = paths.raw / Path(archive.url).name
        if not quiet:
            print(f"\n[{archive.key}] {archive.url}")
        download_file(archive.url, zip_path, force=force, quiet=quiet)
        manifest["archives"].append(
            {
                "key": archive.key,
                "url": archive.url,
                "file": zip_path.name,
                "bytes": zip_path.stat().st_size,
                "sha256": sha256(zip_path),
                "covers_years": list(archive.years),
            }
        )
        if download_only:
            continue

        extracted = extract_archive(zip_path, paths.interim, force=force)
        for year in sorted(set(archive.years) & wanted):
            unit = extracted.unit(year)
            if unit is None:
                if not quiet:
                    print(f"  ! {year}: no DEFUN table in archive, skipping")
                continue
            manifest["tables"].append(
                _process_year(unit, paths, formats, force=force, quiet=quiet)
            )

        if not keep_zip:
            zip_path.unlink(missing_ok=True)

    manifest["tables"].sort(key=lambda t: t["year"])
    (paths.processed / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )
    return manifest


def _process_year(
    unit: YearUnit, paths: Paths, formats: list[str], *, force: bool, quiet: bool
) -> dict:
    result = convert_dbf(
        unit.main_dbf,
        paths.processed,
        stem=f"defunciones_registradas_{unit.year}",
        formats=formats,
        force=force,
        quiet=quiet,
    )
    catalog_out = paths.catalogos / str(unit.year)
    catalog_files: list[str] = []
    for name, dbf in unit.catalogs.items():
        try:
            res = convert_dbf(
                dbf, catalog_out, stem=name.lower(), formats=formats, force=force, quiet=quiet
            )
            catalog_files.extend(str(p.relative_to(paths.root)) for p in res.outputs)
        except Exception as exc:  # noqa: BLE001 - catalogs are best-effort
            if not quiet:
                print(f"  ! catalog {name}: {exc}")

    if not quiet:
        print(f"  ✓ {unit.year}: {result.rows:,} rows")
    return {
        "year": unit.year,
        "source_dbf": unit.main_dbf.name,
        "rows": result.rows,
        "outputs": [str(p.relative_to(paths.root)) for p in result.outputs],
        "catalogs": sorted(catalog_files),
        "descriptors": [str(p.relative_to(paths.root)) for p in unit.extras],
    }
