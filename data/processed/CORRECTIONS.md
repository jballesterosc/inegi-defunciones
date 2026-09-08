# Manual corrections to processed data

This file records hand edits made to files under `data/processed/` that are
**not** reproducible by re-running the pipeline from the INEGI source archives.
Keep it append-only.

---

## 2026-09-08 — 2020 Lista Mexicana catalog: add COVID-19 code `06T`

**File:** `data/processed/catalogos/2020/listamex.parquet`

**What was missing:** the code `06T` ("COVID-19") was absent from the 2020
`listamex` (Lista Mexicana de Enfermedades) catalog.

**Why:** INEGI introduced `06T` in the Lista Mexicana catalog starting with the
**2021** vintage. The 2020 catalog, as published by INEGI, predates that
addition and has no entry for it. (The 2020 `listamex` catalog has 418 rows;
the 2021 one has 422 and includes `06T` -> `COVID-19` plus the vaccine-adverse
codes `57A` / `61`.)

**Impact:** the 2020 microdata file
`data/processed/defunciones_registradas_2020.parquet` uses
`LISTA_MEX == '06T'` for **200,270** records (the single most frequent cause
code that year). Any join of the 2020 microdata onto the 2020 `listamex`
catalog on `LISTA_MEX` silently dropped all 200,270 COVID-19 rows.

**What was added:** one row, `CVE = '06T'`, `DESCRIP = 'COVID-19'`. The
description string is copied verbatim from the 2021 `listamex` catalog's `06T`
row. The 2020 catalog is sorted ascending by `CVE`, so the row was inserted in
its sorted position (index 72, i.e. the 73rd row) between `06S` and `06Z`. The
other 418 rows are unchanged and in their original order.

Row count: **418 -> 419**.

**How:** written with `pyarrow` 25.0.1, `pq.write_table(..., compression="zstd")`
— same schema (`CVE: string`, `DESCRIP: string`), format version, and codec as
the pipeline's own output.

**manifest.json:** not modified. It records per-year source-DBF row counts for
the main tables and lists catalog file paths, but carries no per-catalog-file
row counts or checksums, so there is nothing catalog-specific to update.
