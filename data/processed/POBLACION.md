# Population denominators (CONAPO)

State-level population for turning EDR death counts into rates.

## Source

CONAPO — *Proyecciones de la Población de México y de las Entidades Federativas*.
Resource: **"Población a mitad de año, 1950–2070"**.

- Dataset page: <https://www.datos.gob.mx/dataset/proyecciones-de-poblacion/resource/de522924-f4d8-4523-a6fd-6b2efe73f3af>
- Direct download: <https://repodatos.atdt.gob.mx/CONAPO/proyecciones/00_Pob_Mitad_1950_2070.csv>
- Retrieved 2026-09-08. `sha256(poblacion_entidades.csv)` =
  `89db6adc7930965fb5b5c01ad3a98765ed90afa6a151c2cfb913acc2b9e0cac6`
  (byte-identical to the official file).

Official description: *"Estimación del monto poblacional anual con fecha al
primero de Julio desagregado por edad y sexo. Disponible a nivel nacional
(1950–2070) y entidad federativa (1970–2070)."*

- **Reference date: 1 July** (mid-year / "a mitad de año").
- This particular CSV contains **only the entidad-federativa level, 1970–2070**
  (its `RENGLON` starts at 4621; national rows are elsewhere in the dataset).
- Grain: entity × single-year age (0–109) × sex × year.
- The file's `FECHA` column literally reads `YYYY-01-01` for every row — that
  is a quirk of the published file; the values are the 1 July estimates
  (they reproduce CONAPO's published mid-year totals exactly, e.g. national
  2020 = 128,209,170, Aguascalientes 2020 = 1,456,050).

Raw extract: `poblacion_entidades.csv` (711,040 rows; columns `RENGLON, ANIO,
ENTIDAD, CVE_GEO, EDAD, SEXO, POBLACION, ENTIDAD_FEDERATIVA, FECHA`).
**Not committed** (43 MB, `.gitignore`d) — re-download from the URL above; the
derived parquet below carries the same data.

## Files

| file | grain | rows | in git | use |
|---|---|---|---|---|
| `poblacion_entidades.csv` | anio × entidad × edad × sexo | 711,040 | no (gitignored) | raw source, as provided |
| `poblacion_entidades.parquet` | anio × entidad × edad × sexo | 711,040 | yes | typed source: `anio` i16, `cve_entidad` str, `entidad` str, `edad` i16 (0–109), `sexo` str (`Hombres`/`Mujeres`), `poblacion` i64 |
| `poblacion_entidades_totales.parquet` | anio × entidad | 3,232 | yes | convenience aggregate (both sexes, all ages summed) for crude rates |

The two parquet files are rebuilt from the CSV; if you re-download a fresh CSV,
regenerate them (drop `RENGLON` and `FECHA`, zero-pad `CVE_GEO`, sum for the
totals file).

## Joining to the EDR microdata

`cve_entidad` is zero-padded (`"01"`–`"32"`) to match the `ENT_REGIS` /
`ENT_RESID` / `ENT_OCURR` string columns in `defunciones_registradas_<year>.parquet`.
`entidad` uses CONAPO's `ENTIDAD_FEDERATIVA` label, so state 15 is
`"Estado de México"` (not the bare `"México"`).

The EDR files have no bare year column — use `ANIO_OCUR` (year of death) for
mortality rates, or `ANIO_REGIS` (year of registration, = the file's year).

Crude death rate per 100k, by state-year of occurrence:

```sql
SELECT d.anio, d.ent, 1e5 * d.muertes / p.poblacion AS tasa_100k
FROM (SELECT ANIO_OCUR anio, ENT_OCURR ent, count(*) muertes
      FROM 'defunciones_registradas_*.parquet'
      WHERE ENT_OCURR BETWEEN '01' AND '32'
      GROUP BY 1, 2) d
JOIN 'poblacion_entidades_totales.parquet' p
  ON p.anio = d.anio AND p.cve_entidad = d.ent;
```

Note: deaths occurring in year Y but registered in Y+1 land in the Y+1 file, so
the most recent year undercounts slightly until the next vintage.

## Coverage vs EDR

EDR microdata here is 2005–2024; this population series covers 1970–2070, so
every EDR year has a denominator. These are projections, not census counts —
2020 differs from the 2020 Census.
