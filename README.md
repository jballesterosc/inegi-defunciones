# inegi-defunciones

Scraper for INEGI's **Estadísticas de Defunciones Registradas (EDR)** — the
record-level mortality microdata for Mexico published as open data at
<https://www.inegi.org.mx/programas/edr/#datos_abiertos>.

It downloads the yearly (and multi-year bundle) DBF archives, extracts them, and
converts each year's main table (`DEFUN<yy>.dbf`, one row per registered death,
~74 coded columns) to **Parquet** and/or **CSV**. Lookup/catalog tables shipped
in the archives (localities, ICD chapter groups, occupations, languages,
countries, …) are converted too.

The archives are public files — **no API key is required.**

## Data layout

INEGI publishes:

| Years        | Archive                                                              |
|--------------|---------------------------------------------------------------------|
| 2020–2024    | one zip per year (`defunciones_base_datos_<year>_dbf.zip`)           |
| 1990–2019    | 5-year bundles (`defunciones_generales_base_datos_<a>_<b>_dbf.zip`)  |

The built-in catalog (`inegi_defunciones/catalog.py`) hard-codes the URLs that
work today; `--refresh-catalog` re-derives them from INEGI's own "descarga
masiva" listing API in case they move.

## Install

```bash
uv venv --python 3.12
uv pip install -e .          # add ".[dev]" for the test deps
```

(or `pip install -e .` in a virtualenv). Requires Python ≥ 3.10; deps are
`requests`, `numpy`, `pyarrow`, `tqdm`.

## Usage

```bash
# Last 20 years (2005–2024) -> Parquet, into ./data/processed/
inegi-defunciones run

# A specific span, as Parquet + CSV
inegi-defunciones run --start-year 2015 --end-year 2024 --format both

# Specific years
inegi-defunciones run --years 2000,2010,2018-2020

# Just fetch the zip archives
inegi-defunciones run --download-only

# Inspect what will be downloaded
inegi-defunciones catalog
inegi-defunciones catalog --refresh
```

### Output tree

```
data/
├── raw/                       downloaded .zip archives (kept unless --drop-zip)
├── interim/<key>/             extracted .dbf + descriptor PDFs
└── processed/
    ├── defunciones_registradas_<year>.parquet   one row per registered death
    ├── catalogos/<year>/<name>.parquet          that year's lookup tables
    └── manifest.json                            URLs, sizes, sha256, row counts
```

Rough scale: ~550 MB of zips for 1990–2024; ~800k–1M rows per recent year.
Parquet (zstd) is ~15–20 MB/year, CSV ~230 MB/year. INEGI's server is slow
(~300 KB/s), so a full 20-year download takes a while — it is resumable.

### Disposable vs. keep

- **`data/interim/` is disposable.** It holds only the DBFs (and descriptor
  PDFs) unzipped from `data/raw/`; for 2005–2024 that is ~1.9 GB. Delete it any
  time to reclaim space — it is `.gitignore`d and is never committed.

  Rebuild it from the zips already in `data/raw/`, without re-downloading and
  without touching the Parquet in `data/processed/`:

  ```bash
  inegi-defunciones run        # zips present -> no download; parquet present -> no re-convert;
                               # just re-extracts data/interim/ and rewrites manifest.json
  ```

  (`download_file` skips any zip that already exists; `convert_dbf` skips any
  Parquet that already exists. Add `--force` only if you want them rebuilt.)

- **`data/raw/*.zip` must never be deleted.** Those eight archives are the only
  copy of the source: the INEGI datos-abiertos URLs in `manifest.json` are the
  single upstream, no mirror is known, and a dead URL cannot be assumed to come
  back. `manifest.json` records each URL + SHA-256 for verification, not as a
  fallback. Deleting a zip loses that vintage of the microdata.

### Options

| Flag | Meaning |
|------|---------|
| `--data-dir DIR` | output root (default `./data`) |
| `--years LIST` | explicit years, e.g. `2015,2018-2020` |
| `--start-year` / `--end-year` | inclusive range (default 2005–2024) |
| `--format {parquet,csv,both}` | converted-table format (default `parquet`) |
| `--download-only` | stop after downloading the zips |
| `--drop-zip` | delete each zip once processed |
| `--refresh-catalog` | resolve URLs from INEGI's listing API |
| `--force` | redo steps whose outputs already exist |
| `--quiet` | no progress bars |

Runs are resumable: completed downloads, extractions and conversions are skipped
on re-run unless `--force` is given. Partial downloads resume from the `.part`
file.

## Notes on the data

- Output is UTF-8. Text is decoded per file from the DBF language-driver byte
  (`cp850` for the DOS-era catalog tables, `cp1252` for newer ones); the main
  `DEFUN` table is pure ASCII codes. Override with `dbf_to_table(..., encoding=)`.
- Numeric DBF fields become nullable `int64` (or `float64` when they carry
  decimals); blank strings become nulls. Column names are kept verbatim.
- The column set grows over time — pre-2020 years have ~59 columns, 2020+ have
  ~74 (added `AFROMEX`, `CONINDIG`, `DIS_RE_OAX`, …). Each year is written to its
  own file; union the schemas yourself if you concatenate across years.
- Values are **coded**, not decoded here. `EDAD` packs a unit digit + magnitude
  (e.g. `4073` = 73 years, `3005` = 5 months); geography is `ENT_*` / `MUN_*` /
  `LOC_*` INEGI keys; cause of death is ICD-10 in `CAUSA_DEF`. See the
  `Descripcion_BD_Defunciones_*.pdf` in `interim/` and the `catalogos/` tables.
- Rows include deaths that *occurred* in earlier years but were *registered* in
  the file's year (`ANIO_OCUR` vs `ANIO_REGIS`).
- INEGI renamed this program from *Defunciones generales* (mortalidad) to
  *Estadísticas de Defunciones Registradas* in 2022; older bundles keep the old
  `defunciones_generales_...` filename stem.

## License

MIT. The data belongs to INEGI and is governed by its
[términos de libre uso](https://www.inegi.org.mx/inegi/terminos.html).
