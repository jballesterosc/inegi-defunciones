"""Registry of INEGI EDR microdata source archives.

INEGI publishes the *Estadísticas de Defunciones Registradas* (EDR, formerly
"Defunciones generales / mortalidad") record-level microdata as zipped DBF files
on its "datos abiertos" pages:

    https://www.inegi.org.mx/programas/edr/#datos_abiertos

Recent years are published one archive per year; older years are grouped into
5-year bundles. This module maps a requested calendar year to the archive that
contains it, and can optionally refresh that map from INEGI's "descarga masiva"
listing API so the code keeps working if the URLs move.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

import requests

MICRODATA_BASE = "https://www.inegi.org.mx/contenidos/programas/edr/microdatos/defunciones"

# INEGI internal program id for EDR, used by the descarga-masiva listing API.
EDR_PROGRAM_ID = "2658"
DESCARGA_LIST_API = (
    "https://www.inegi.org.mx/app/api/descarga/descarga/descargamasiva/lista"
    "/obtenerlistaarchivosdescarga"
)
DESCARGA_FETCH_BASE = "https://www.inegi.org.mx/app/api"

USER_AGENT = "inegi-defunciones/0.1 (+https://github.com/) python-requests"


@dataclass(frozen=True)
class SourceArchive:
    """One downloadable zip and the calendar years it covers."""

    key: str  # stable local name, e.g. "2023" or "2015_2019"
    url: str
    years: tuple[int, ...]

    @property
    def is_bundle(self) -> bool:
        return len(self.years) > 1


def _individual(year: int) -> SourceArchive:
    return SourceArchive(
        key=str(year),
        url=f"{MICRODATA_BASE}/{year}/defunciones_base_datos_{year}_dbf.zip",
        years=(year,),
    )


def _bundle(start: int, end: int) -> SourceArchive:
    return SourceArchive(
        key=f"{start}_{end}",
        url=(
            f"{MICRODATA_BASE}/datos/"
            f"defunciones_generales_base_datos_{start}_{end}_dbf.zip"
        ),
        years=tuple(range(start, end + 1)),
    )


# Verified working against inegi.org.mx as of 2026-09. `refresh_catalog()` can
# regenerate this list from INEGI's own API.
DEFAULT_ARCHIVES: tuple[SourceArchive, ...] = (
    _bundle(1990, 1994),
    _bundle(1995, 1999),
    _bundle(2000, 2004),
    _bundle(2005, 2009),
    _bundle(2010, 2014),
    _bundle(2015, 2019),
    _individual(2020),
    _individual(2021),
    _individual(2022),
    _individual(2023),
    _individual(2024),
)


@dataclass
class Catalog:
    archives: tuple[SourceArchive, ...] = field(default_factory=lambda: DEFAULT_ARCHIVES)

    @property
    def available_years(self) -> tuple[int, ...]:
        years: set[int] = set()
        for a in self.archives:
            years.update(a.years)
        return tuple(sorted(years))

    def archives_for_years(self, years: list[int]) -> list[SourceArchive]:
        """Return the minimal set of archives needed to cover ``years``.

        Raises ``KeyError`` listing any requested year with no known archive.
        """
        wanted = set(years)
        selected: list[SourceArchive] = []
        covered: set[int] = set()
        for archive in self.archives:
            if wanted & set(archive.years):
                selected.append(archive)
                covered.update(archive.years)
        missing = sorted(wanted - covered)
        if missing:
            raise KeyError(
                f"No INEGI archive known for year(s): {missing}. "
                f"Available: {self.available_years[0]}-{self.available_years[-1]}. "
                "Try `--refresh-catalog`."
            )
        return selected


_ARCHIVE_YEAR_RE = re.compile(r"base_datos_(\d{4})(?:_(\d{4}))?_dbf\.zip$", re.IGNORECASE)


def refresh_catalog(timeout: float = 60.0) -> Catalog:
    """Rebuild the catalog from INEGI's descarga-masiva listing API.

    The API hands back a path to a generated zip that bundles a Windows
    downloader and an XML manifest (``DescargaMasivaOD.xml``) listing every
    file URL for the program. We only need the manifest.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.inegi.org.mx/app/descarga/",
            "Content-Type": "application/json",
        }
    )
    payload = {
        "subtema": "0",
        "areaGeografica": "0",
        "proyecto": "0",
        "tipoInformacion": "0",
        "periodo": "0",
        "formato": "0",
        "datosAbiertos": "3",
        "textoBuscar": "",
        "ingles": "0",
        "programa": EDR_PROGRAM_ID,
    }
    resp = session.post(DESCARGA_LIST_API, json=payload, timeout=timeout)
    resp.raise_for_status()
    manifest_path = resp.text.strip()
    if not manifest_path.startswith("/"):
        raise RuntimeError(f"Unexpected listing API response: {manifest_path[:200]!r}")

    zresp = session.get(DESCARGA_FETCH_BASE + manifest_path, timeout=timeout)
    zresp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(zresp.content)) as zf:
        xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
        xml_bytes = zf.read(xml_name)

    root = ElementTree.fromstring(xml_bytes)
    archives: list[SourceArchive] = []
    for node in root.iterfind(".//Archivo"):
        url = (node.text or "").strip()
        if "/microdatos/" not in url:
            continue
        m = _ARCHIVE_YEAR_RE.search(url)
        if not m:
            continue
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        archives.append(
            SourceArchive(
                key=str(start) if start == end else f"{start}_{end}",
                url=url,
                years=tuple(range(start, end + 1)),
            )
        )
    if not archives:
        raise RuntimeError("No microdata archives found in INEGI manifest")
    archives.sort(key=lambda a: a.years[0])
    return Catalog(archives=tuple(archives))
