# Aggregate table — deaths by cause, sex, age group (occurrence years 2005–2024)

Built by `scripts/build_aggregate.py` on 2026-09-09. Row-per-death → counts + crude
rates. No inference, no analysis, no age-standardization.

## Files

| file | what |
|---|---|
| `defunciones_agregado_2005_2024.parquet` | the aggregate table (221,735 rows) |
| `defunciones_rezago_registro.csv` | source-file year × occurrence year (registration lag) |
| `crosswalk_edad_agru_conapo.csv` | EDAD_AGRU ↔ CONAPO single-year ages |
| `lista_mex_labels_por_anio.csv` | every LISTA_MEX code × its label in each of the 20 catalog vintages |

## Grain (one row per)

`anio_ocur` · `lista_mex` · `lista1` · `capitulo` · `grupo` · `sexo` · `edad_agru`

Measures: `defunciones` (count), `poblacion` (CONAPO denominator), `tasa_100k`
(= 100000 · defunciones / poblacion), `provisional` (bool).
Labels: `lista_mex_desc`, `lista_mex_desc_anio_fuente`, `sexo_desc`,
`edad_agru_desc`, `prefijo`.

`lista1` / `capitulo` / `grupo` are **not** functionally determined by
`lista_mex` — 41 codes (mostly the `…Z` residual codes) span more than one
(`lista1`,`capitulo`,`grupo`) combination — so they sit **in the grain**, not as
carried single values. Nothing was collapsed, dropped, or invented; the count
column still reconciles exactly (Gate 3).

`prefijo` is the numeric stem of `lista_mex` (`27Z` → `27`), for grouping
related codes later.

## Year convention (D1)

The year key is **year of occurrence** (`ANIO_OCUR`), not registration.

- `ANIO_OCUR == 9999` (sentinel for unknown) → `anio_ocur = 'desconocido'`.
  9999 never becomes a number. **4032** rows, by source-file year:
  2005:32, 2006:38, 2007:48, 2008:31, 2009:302, 2010:39, 2011:144, 2012:128, 2013:140, 2014:188, 2015:142, 2016:139, 2017:130, 2018:377, 2019:209, 2020:688, 2021:306, 2022:332, 2023:287, 2024:332.
- `provisional = TRUE` for occurrence year **2024** only. Deaths that occurred in
  2024 but were registered in 2025 are not in this data yet, so 2024 is
  undercounted by roughly 2% (see the lag table — every complete year shows
  ~2.0–2.5% of its deaths registered in a later year; 2024 shows 0%).
- Occurrence years **before 2005** (24,367 rows) and `desconocido` are kept
  (Gate 3 forbids dropping rows) but are **not** complete counts — they are only
  the late registrations that happened to fall inside the 2005–2024 registration
  windows. Their `tasa_100k` is NULL.

## Catalog join (D2) and labels

The **validity join** (Gate 2) is per registration year:
`anio_archivo` + trimmed `LISTA_MEX` ↔ `anio_catalogo` + trimmed `clave`
(`clave` = COALESCE(`CLAVE`,`CVE`)). Not one master catalog.

**`lista_mex_desc` is the label from the OCCURRENCE year's catalog** (D1-aligned),
never a single collapsed label. `lista_mex_desc_anio_fuente` is the catalog year
that label came from; it equals `anio_ocur` except when the occurrence year is
outside that code's catalog coverage — before the code's first vintage, after
its last, or `desconocido` — in which case the nearest covered year is used.
**13,044** rows use such a fallback, and **every one is an occurrence
year before 2005 or `desconocido`** (0 rows inside the target
range 2005–2024 use a fallback) — so within scope the label is always the code's
own occurrence-year wording.

Wording drift across the 20 vintages: **1** code(s).
- `06S` (1 death total): 2016: 'Enfermedad por el virus del Zika, sin especificación'  →  2021: 'Enfermedad por el virus del Zika'
The full per-vintage label history for all 422 catalog codes is in
`lista_mex_labels_por_anio.csv` (column `cambio_vs_anio_previo`) — a string diff
catches renamed codes, not a code silently reused for a different concept, so
check that file directly rather than trusting this count.

`lista1` is NULL for **227** aggregate rows: codes
['06T', '57A'] (COVID-19 and the
COVID-vaccine adverse-effect code) were given no `LISTA1` value by INEGI in the
2022–2024 catalog vintages. Left NULL, not invented.

## Population denominator

CONAPO **"Proyecciones de la Población … 2020–2070" (revisión 2023)**,
población a mitad de año — `data/processed/poblacion_entidades.parquet`
(entidad × single-year age 0–109 × sex × year 1970–2070). See
`data/processed/POBLACION.md`. National figures = sum of the 32 entidades.

Join grain: **year × sex × age group** (option c — the finest CONAPO supports).

### Age crosswalk decisions (`crosswalk_edad_agru_conapo.csv`)

- `01`–`26` map cleanly: `01`→age 0, `02`→1, `03`→2, `04`→3, `05`→4,
  `06`→5–9, …, `25`→100–104, `26`→105–109.
- `27` (110–114), `28` (115–119), `29` (120+): **no mapping** — CONAPO stops at
  age 109. `tasa_100k` left NULL. ~1,000 deaths over 20 years.
- `30` (No especificada): **no mapping** — unknown age has no denominator.
  `tasa_100k` NULL.
- `SEXO = 9` (No especificado): no CONAPO sex category. `tasa_100k` NULL.

No age mapping was forced or invented.

`tasa_100k` is NULL for **8,630** rows total (`anio_ocur='desconocido'`,
`sexo=9`, `edad_agru` 27/28/29/30, or occurrence year before 1970).

## Gate results

| gate | result |
|---|---|
| **1** catalog union | **8366** rows (= 8365 + the documented 06T patch to the 2020 catalog), **20** distinct years. Per-year: 417 (2005–2015), 418 (2016–2019), **419 (2020)**, 422 (2021–2024). |
| **2** per-year validity join | joined rows == source rows for **every** year; **diff 0** throughout; **0** unmatched codes. |
| **3** count reconciliation | sum(defunciones) = **13,841,784** = total rows of the 20 source files (13,841,784). Dated 13,837,752 + desconocido 4,032. |
| **4** population coverage | present & plausible for all 20 years; **0** in-scope death rows missing a denominator. ~106.4M (2005) → ~132.3M (2024). |

### Gate 2 detail (year: source = joined, diff)
- 2005: 495,240 = 495,240, diff 0
- 2006: 494,471 = 494,471, diff 0
- 2007: 514,420 = 514,420, diff 0
- 2008: 539,530 = 539,530, diff 0
- 2009: 564,673 = 564,673, diff 0
- 2010: 592,018 = 592,018, diff 0
- 2011: 590,693 = 590,693, diff 0
- 2012: 602,354 = 602,354, diff 0
- 2013: 623,599 = 623,599, diff 0
- 2014: 633,641 = 633,641, diff 0
- 2015: 655,688 = 655,688, diff 0
- 2016: 685,766 = 685,766, diff 0
- 2017: 703,047 = 703,047, diff 0
- 2018: 722,611 = 722,611, diff 0
- 2019: 747,784 = 747,784, diff 0
- 2020: 1,086,743 = 1,086,743, diff 0
- 2021: 1,122,249 = 1,122,249, diff 0
- 2022: 847,716 = 847,716, diff 0
- 2023: 799,869 = 799,869, diff 0
- 2024: 819,672 = 819,672, diff 0

### Gate 4 detail (occurrence-year totals & crude rate, both sexes / all ages)
| occ year | deaths | national pop | crude /100k |
|---|---|---|---|
| 2005 | 496,174 | 106,370,948 | 466.5 |
| 2006 | 494,146 | 107,885,646 | 458.0 |
| 2007 | 514,327 | 109,538,665 | 469.5 |
| 2008 | 539,199 | 111,275,915 | 484.6 |
| 2009 | 564,099 | 113,030,218 | 499.1 |
| 2010 | 593,515 | 114,756,059 | 517.2 |
| 2011 | 590,436 | 116,446,180 | 507.0 |
| 2012 | 603,064 | 118,060,514 | 510.8 |
| 2013 | 622,794 | 119,597,654 | 520.7 |
| 2014 | 632,214 | 121,048,604 | 522.3 |
| 2015 | 654,339 | 122,368,490 | 534.7 |
| 2016 | 685,677 | 123,587,407 | 554.8 |
| 2017 | 704,879 | 124,777,172 | 564.9 |
| 2018 | 722,971 | 125,995,825 | 573.8 |
| 2019 | 745,654 | 127,215,666 | 586.1 |
| 2020 | 1,093,398 | 128,209,170 | 852.8 |
| 2021 | 1,117,935 | 128,982,939 | 866.7 |
| 2022 | 843,782 | 129,960,600 | 649.3 |
| 2023 | 797,216 | 131,135,337 | 607.9 |
| 2024 | 797,566 | 132,274,416 | 603.0 |

(2024 is provisional — see above.)

## Unmatched cause codes

None. Every `LISTA_MEX` value in every death file resolves in that year's
`listamex` catalog.

## Open items — DO NOT PUBLISH until closed

**COVID-19 (`06T`) counts are not externally reconciled.** This table's `06T`
totals by occurrence year are 201,307 (2020) and 238,173 (2021). These were
compared only against INEGI's *preliminary* press releases — Comunicado 402/21
(29 Jul 2021): COVID-19 = 201,163 registered in 2020; INEGI preliminary EDR 2021
(27 Jul 2022): COVID-19 = 224,239 registered in 2021. That is a
**preliminary-vs-definitive, registration-vs-occurrence** comparison, **not a
true reconciliation**: the 2021 figures differ by ~14,000 (~6%). The definitive
INEGI cause-of-death tabulation for full-year 2020 and 2021 was **not located**.
**No COVID-19 figure derived from this table should be published** until that
definitive source is found and the gap is explained or closed.

## Console log

```
==============================================================================
STEP 1 - COMBINE
==============================================================================
death union rows            : 13,841,784
death union source-file yrs : [2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]
catalog union rows         : 8366   (key column normalized CLAVE/CVE -> 'clave')

------------------------------------------------------------------------------
GATE 1  catalog union == 8365 rows AND exactly 20 years
------------------------------------------------------------------------------
catalog union row count : 8366
distinct catalog years  : 20
rows / catalog year     : 2005:417, 2006:417, 2007:417, 2008:417, 2009:417, 2010:417, 2011:417, 2012:417, 2013:417, 2014:417, 2015:417, 2016:418, 2017:418, 2018:418, 2019:418, 2020:419, 2021:422, 2022:422, 2023:422, 2024:422
GATE 1 NOTE: 8366 != 8365 (diff 1). The 2020 catalog holds 419 rows, not 418: it was patched to add 06T (COVID-19), which INEGI first shipped in the 2021 catalog. The task's KNOWN FACTS acknowledge that patch; the '8365 / 2020=418' figure predates it. The extra row IS the documented patch, not a data fault. Proceeding.
GATE 1 result: 20 years OK; 8366 rows = 8365 + documented 06T patch to 2020.

==============================================================================
STEP 2 - JOIN LABELS   deaths(anio_archivo, lm_key)  <->  cat(anio_catalogo, clave)
==============================================================================
joined rows : 13,841,784   (== death union 13,841,784)

------------------------------------------------------------------------------
GATE 2  per source-file year: joined rows == source rows (diff 0)
------------------------------------------------------------------------------
  year   source_rows   joined_rows   diff
  2005       495,240       495,240      0
  2006       494,471       494,471      0
  2007       514,420       514,420      0
  2008       539,530       539,530      0
  2009       564,673       564,673      0
  2010       592,018       592,018      0
  2011       590,693       590,693      0
  2012       602,354       602,354      0
  2013       623,599       623,599      0
  2014       633,641       633,641      0
  2015       655,688       655,688      0
  2016       685,766       685,766      0
  2017       703,047       703,047      0
  2018       722,611       722,611      0
  2019       747,784       747,784      0
  2020     1,086,743     1,086,743      0
  2021     1,122,249     1,122,249      0
  2022       847,716       847,716      0
  2023       799,869       799,869      0
  2024       819,672       819,672      0
rows with no catalog label (unmatched code): 0
GATE 2 result: every source-file year joins 1:1; zero unmatched codes.
codes whose catalog wording changed across the 20 vintages: 1
   06S  2016:'Enfermedad por el virus del Zika, sin especificación' -> 2021:'Enfermedad por el virus del Zika'
wrote data/processed/lista_mex_labels_por_anio.csv (8366 rows, 422 codes) - full per-vintage label history

==============================================================================
STEP 3 - HANDLE THE YEAR KEY (file year -> occurrence year)
==============================================================================

3a. ANIO_OCUR == 9999 by source-file year (kept; year label -> 'desconocido'):
    2005:    32
    2006:    38
    2007:    48
    2008:    31
    2009:   302
    2010:    39
    2011:   144
    2012:   128
    2013:   140
    2014:   188
    2015:   142
    2016:   139
    2017:   130
    2018:   377
    2019:   209
    2020:   688
    2021:   306
    2022:   332
    2023:   287
    2024:   332
    total: 4032

3b. registration-lag side table: source-file year x occurrence year -> CSV
    wrote data/processed/defunciones_rezago_registro.csv (1464 rows)

3c. share of each occurrence year registered in a LATER file year (expect ~2%):
    occ_year       deaths    reg_later    share
        2005      496,174       10,798   2.18%
        2006      494,146       10,968   2.22%
        2007      514,327       11,005   2.14%
        2008      539,199       11,106   2.06%
        2009      564,099       12,033   2.13%
        2010      593,515       13,814   2.33%
        2011      590,436       13,774   2.33%
        2012      603,064       15,238   2.53%
        2013      622,794       14,912   2.39%
        2014      632,214       14,117   2.23%
        2015      654,339       13,449   2.06%
        2016      685,677       14,141   2.06%
        2017      704,879       16,411   2.33%
        2018      722,971       17,822   2.47%
        2019      745,654       16,597   2.23%
        2020    1,093,398       23,440   2.14%
        2021    1,117,935       19,634   1.76%
        2022      843,782       17,952   2.13%
        2023      797,216       17,977   2.25%
        2024      797,566            0   0.00%
    occurrence years < 2005 (real): 24,367 deaths - late registrations only, NOT complete counts for those years.

==============================================================================
STEP 4 - AGGREGATE
==============================================================================
grain: anio_ocur | lista_mex | lista1 | capitulo | grupo | sexo | edad_agru
lista_mex_desc = label from the OCCURRENCE year's catalog (D1-aligned), not one
collapsed label. lista_mex_desc_anio_fuente records which catalog year it came from
(differs from anio_ocur only when the occurrence year is outside the code's catalog
coverage). Full per-vintage history is in lista_mex_labels_por_anio.csv.
NOTE: LISTA1/CAPITULO/GRUPO are NOT functionally determined by LISTA_MEX: 41 codes (mostly 'Z' residual codes) span >1 (LISTA1,CAPITULO,GRUPO) combo. They are therefore kept IN the grain, not collapsed to one value. No row dropped, no value invented; the count column still sums exactly (GATE 3).
aggregate rows: 221,735
aggregate rows whose label came from a fallback catalog year: 13,044 (0 of them inside 2005-2024)
deaths under the 1 code(s) with any wording change: 1
aggregate rows with NULL cause label : 0
aggregate rows with NULL lista1      : 227  (codes ['06T', '57A'] - no LISTA1 assigned by INEGI in the relevant catalog vintages; left NULL, not invented)

------------------------------------------------------------------------------
GATE 3  sum(defunciones) + 'desconocido' == total rows of all 20 files
------------------------------------------------------------------------------
sum(defunciones), dated year rows : 13,837,752
sum(defunciones), 'desconocido'   : 4,032
sum(defunciones), total           : 13,841,784
total rows, 20 source files       : 13,841,784
GATE 3 result: exact match.

==============================================================================
STEP 5 - ADD POPULATION
==============================================================================
5a. CONAPO file: data/processed/poblacion_entidades.parquet
    columns  : [('anio', 'int16'), ('cve_entidad', 'string'), ('entidad', 'string'), ('edad', 'int16'), ('sexo', 'string'), ('poblacion', 'int64')]
    row count: 711,040
    structure: 32 entidades x 101 years (1970-2070) x 110 single-year ages (0-109) x 2 sexes ['Hombres', 'Mujeres']
    supports (a) year only, (b) year+sex, AND (c) year+sex+age group.
    -> joining at (c), the finest grain. National = sum of the 32 entidades;
       single-year ages are folded into EDAD_AGRU groups via the crosswalk.

5b. EDAD_AGRU <-> CONAPO age crosswalk -> CSV
    wrote data/processed/crosswalk_edad_agru_conapo.csv
    01-26 map cleanly to single-year ages 0 .. 105-109.
    UNMAPPED (rate left NULL): ['27', '28', '29', '30']  -- 27/28/29 = ages 110+ (CONAPO max 109); 30 = age not stated.  SEXO=9 also has no CONAPO denominator -> rate NULL.

5c. national population table: 5,252 (anio, sexo, edad_agru) cells

------------------------------------------------------------------------------
GATE 4  population present for all 20 target years 2005-2024
------------------------------------------------------------------------------
  year  poblacion_total   (national, both sexes, mapped groups 01-26)
  2005      106,370,948
  2006      107,885,646
  2007      109,538,665
  2008      111,275,915
  2009      113,030,218
  2010      114,756,059
  2011      116,446,180
  2012      118,060,514
  2013      119,597,654
  2014      121,048,604
  2015      122,368,490
  2016      123,587,407
  2017      124,777,172
  2018      125,995,825
  2019      127,215,666
  2020      128,209,170
  2021      128,982,939
  2022      129,960,600
  2023      131,135,337
  2024      132,274,416
eyeball: ~106M (2005) -> ~132M (2024). CONAPO 'Proyecciones 2020-2070' rev. 2023,
mid-year; ~3% above older census-based guesses (103M / 128M) because rev. 2023
revised the series upward.
in-scope death rows missing a denominator (must be 0): 0
GATE 4 result: population present and plausible for all 20 years.

==============================================================================
STEP 6 - OUTPUT
==============================================================================
wrote data/processed/defunciones_agregado_2005_2024.parquet
  rows=221,735  sum(defunciones)=13,841,784
  NULL tasa_100k rows: 8,630
```
