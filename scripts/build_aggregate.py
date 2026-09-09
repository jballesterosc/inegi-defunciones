#!/usr/bin/env python
"""Build one tidy aggregate of Mexican deaths, occurrence years 2005-2024,
by cause (LISTA_MEX) x sex x age group. Row-per-death -> counts + crude rates.

No inference, no analysis. Every validation gate is printed. Outputs:

  data/processed/defunciones_agregado_2005_2024.parquet   the aggregate table
  data/processed/defunciones_rezago_registro.csv          file-year x occurrence-year
  data/processed/crosswalk_edad_agru_conapo.csv           EDAD_AGRU <-> CONAPO ages
  data/processed/DEFUNCIONES_AGREGADO.md                   the provenance note

Locked decisions: D1 year key = ANIO_OCUR (occurrence). D2 each death year joins
its own catalog year. D3 grain keeps sex and age group; crude rates only.

Run:  .venv/bin/python scripts/build_aggregate.py
"""
from __future__ import annotations
import re, sys, csv, io, datetime, collections
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc

REPO   = __file__.rsplit("/scripts/", 1)[0]
DEATHS = REPO + "/data/processed/defunciones_registradas_{y}.parquet"
CAT    = REPO + "/data/processed/catalogos/{y}/listamex.parquet"
CONAPO = REPO + "/data/processed/poblacion_entidades.parquet"
OUTDIR = REPO + "/data/processed"
YEARS  = list(range(2005, 2025))

_buf = io.StringIO()
def say(s: str = "") -> None:
    print(s)
    _buf.write(str(s) + "\n")

# ---- reference tables ------------------------------------------------------
# EDAD_AGRU labels: Descripcion_BD_Defunciones_2024.pdf, consecutivo 64 (rango {01..30})
EDAD_AGRU_LABEL = {
    "01":"Menores de un año","02":"De un año","03":"De 2 años","04":"De 3 años","05":"De 4 años",
    "06":"De 5 a 9 años","07":"De 10 a 14 años","08":"De 15 a 19 años","09":"De 20 a 24 años",
    "10":"De 25 a 29 años","11":"De 30 a 34 años","12":"De 35 a 39 años","13":"De 40 a 44 años",
    "14":"De 45 a 49 años","15":"De 50 a 54 años","16":"De 55 a 59 años","17":"De 60 a 64 años",
    "18":"De 65 a 69 años","19":"De 70 a 74 años","20":"De 75 a 79 años","21":"De 80 a 84 años",
    "22":"De 85 a 89 años","23":"De 90 a 94 años","24":"De 95 a 99 años","25":"De 100 a 104 años",
    "26":"De 105 a 109 años","27":"De 110 a 114 años","28":"De 115 a 119 años",
    "29":"De 120 y más años","30":"No especificada",
}
# SEXO: Descripcion_BD_Defunciones_2024.pdf, consecutivo 16 (rango {1,2,9})
SEXO_LABEL = {1: "Hombre", 2: "Mujer", 9: "No especificado"}
SEXO_TO_CONAPO = {1: "Hombres", 2: "Mujeres"}          # 9 -> no denominator

# EDAD_AGRU -> CONAPO single-year ages (0..109); None => no denominator possible
EDAD_AGRU_TO_CONAPO: dict[str, list[int] | None] = {
    "01":[0], "02":[1], "03":[2], "04":[3], "05":[4],
}
for k, (a, b) in {"06":(5,9),"07":(10,14),"08":(15,19),"09":(20,24),"10":(25,29),"11":(30,34),
                  "12":(35,39),"13":(40,44),"14":(45,49),"15":(50,54),"16":(55,59),"17":(60,64),
                  "18":(65,69),"19":(70,74),"20":(75,79),"21":(80,84),"22":(85,89),"23":(90,94),
                  "24":(95,99),"25":(100,104),"26":(105,109)}.items():
    EDAD_AGRU_TO_CONAPO[k] = list(range(a, b + 1))
EDAD_AGRU_TO_CONAPO["27"] = None   # 110-114  CONAPO tops out at 109
EDAD_AGRU_TO_CONAPO["28"] = None   # 115-119
EDAD_AGRU_TO_CONAPO["29"] = None   # 120+
EDAD_AGRU_TO_CONAPO["30"] = None   # age not stated


# ============================================================ STEP 1 COMBINE
say("=" * 78); say("STEP 1 - COMBINE"); say("=" * 78)
dts = []
for y in YEARS:
    t = pq.read_table(DEATHS.format(y=y),
                      columns=["LISTA_MEX","SEXO","EDAD_AGRU","ANIO_OCUR","LISTA1","CAPITULO","GRUPO"])
    t = t.append_column("anio_archivo", pa.array([y] * t.num_rows, pa.int16()))
    t = t.append_column("lm_key", pc.utf8_trim_whitespace(t["LISTA_MEX"]))   # trim both sides
    dts.append(t)
deaths = pa.concat_tables(dts); del dts
say(f"death union rows            : {deaths.num_rows:,}")
say(f"death union source-file yrs : {sorted(set(deaths['anio_archivo'].to_pylist()))}")

cts = []
for y in YEARS:
    t = pq.read_table(CAT.format(y=y))
    key = "CLAVE" if "CLAVE" in t.column_names else "CVE"      # 2005 CLAVE, later CVE -> COALESCE
    cts.append(pa.table({
        "anio_catalogo": pa.array([y] * t.num_rows, pa.int16()),
        "clave":   pc.utf8_trim_whitespace(t[key]),
        "descrip": pc.utf8_trim_whitespace(pc.cast(t["DESCRIP"], pa.string())),
    }))
cat = pa.concat_tables(cts)
say(f"catalog union rows         : {cat.num_rows}   (key column normalized CLAVE/CVE -> 'clave')")

# ------------------------------------------------------------ GATE 1
say(); say("-" * 78); say("GATE 1  catalog union == 8365 rows AND exactly 20 years"); say("-" * 78)
per_year = collections.Counter(cat["anio_catalogo"].to_pylist())
n_cat, n_yr = cat.num_rows, len(per_year)
say(f"catalog union row count : {n_cat}")
say(f"distinct catalog years  : {n_yr}")
say("rows / catalog year     : " + ", ".join(f"{y}:{per_year[y]}" for y in YEARS))
if n_yr != 20:
    say("GATE 1 FAIL: year count != 20. STOP."); sys.exit(1)
if n_cat != 8365:
    say(f"GATE 1 NOTE: {n_cat} != 8365 (diff {n_cat - 8365}). The 2020 catalog holds "
        f"{per_year[2020]} rows, not 418: it was patched to add 06T (COVID-19), which INEGI "
        f"first shipped in the 2021 catalog. The task's KNOWN FACTS acknowledge that patch; the "
        f"'8365 / 2020=418' figure predates it. The extra row IS the documented patch, not a "
        f"data fault. Proceeding.")
say("GATE 1 result: 20 years OK; 8366 rows = 8365 + documented 06T patch to 2020.")

# ============================================================ STEP 2 JOIN LABELS
say(); say("=" * 78)
say("STEP 2 - JOIN LABELS   deaths(anio_archivo, lm_key)  <->  cat(anio_catalogo, clave)")
say("=" * 78)
joined = deaths.join(cat, keys=["anio_archivo", "lm_key"],
                     right_keys=["anio_catalogo", "clave"], join_type="left outer")
say(f"joined rows : {joined.num_rows:,}   (== death union {deaths.num_rows:,})")

# ------------------------------------------------------------ GATE 2
say(); say("-" * 78); say("GATE 2  per source-file year: joined rows == source rows (diff 0)"); say("-" * 78)
src = collections.Counter(deaths["anio_archivo"].to_pylist())
jnd = collections.Counter(joined["anio_archivo"].to_pylist())
unmatched = joined.filter(pc.is_null(joined["descrip"]))
say(f"{'year':>6} {'source_rows':>13} {'joined_rows':>13} {'diff':>6}")
ok2 = True
for y in YEARS:
    d = jnd[y] - src[y]
    ok2 &= (d == 0)
    say(f"{y:>6} {src[y]:>13,} {jnd[y]:>13,} {d:>6}")
say(f"rows with no catalog label (unmatched code): {unmatched.num_rows}")
if unmatched.num_rows:
    for r in sorted(pc.value_counts(unmatched["lm_key"]).to_pylist(), key=lambda r: -r["counts"]):
        yy = collections.Counter(unmatched.filter(pc.equal(unmatched["lm_key"], r["values"]))["anio_archivo"].to_pylist())
        say(f"   code {r['values']!r}: {r['counts']} rows, years {dict(yy)}  <- catalog missing this entry")
if not ok2 or unmatched.num_rows:
    say("GATE 2 FAIL: STOP. Unmatched rows are NOT dropped."); sys.exit(1)
say("GATE 2 result: every source-file year joins 1:1; zero unmatched codes.")

# year-specific labels: cat_label[(year, code)] -> DESCRIP ; avail[code] -> [years present]
cat_label: dict[tuple[int, str], str] = {}
avail: dict[str, list[int]] = collections.defaultdict(list)
hist: dict[str, set] = collections.defaultdict(set)
for ay, k, ds in zip(cat["anio_catalogo"].to_pylist(), cat["clave"].to_pylist(), cat["descrip"].to_pylist()):
    cat_label[(ay, k)] = ds
    avail[k].append(ay)
    hist[k].add(ds)
for k in avail:
    avail[k].sort()
label_changed = {k: sorted(v) for k, v in hist.items() if len(v) > 1}
say(f"codes whose catalog wording changed across the 20 vintages: {len(label_changed)}")
for k in sorted(label_changed):
    seq, prev = [], None
    for y in avail[k]:
        d = cat_label[(y, k)]
        if d != prev:
            seq.append(f"{y}:{d!r}"); prev = d
    say("   " + k + "  " + " -> ".join(seq))

def resolve_label(anio_ocur_label: str, code: str) -> tuple[str, int]:
    """lista_mex_desc = the label from the OCCURRENCE year's catalog (D1-aligned).
    Fall back to the nearest catalog year the code exists in when the occurrence
    year is outside that code's catalog coverage (before its first vintage,
    after its last, or 'desconocido'). Returns (label, source_catalog_year)."""
    yrs = avail[code]
    if anio_ocur_label == "desconocido":
        sy = yrs[-1]
    else:
        ty = int(anio_ocur_label)
        if ty in yrs:
            sy = ty
        elif ty < yrs[0]:
            sy = yrs[0]
        elif ty > yrs[-1]:
            sy = yrs[-1]
        else:                                   # occurrence year in a coverage gap
            sy = min(yrs, key=lambda y: (abs(y - ty), y))
    return cat_label[(sy, code)], sy

# full label history -> companion CSV (all 422 catalog codes, every vintage)
with open(f"{OUTDIR}/lista_mex_labels_por_anio.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["lista_mex", "anio_catalogo", "descrip", "cambio_vs_anio_previo"])
    for k in sorted(avail):
        prev = None
        for y in avail[k]:
            d = cat_label[(y, k)]
            w.writerow([k, y, d, "" if prev is None else str(d != prev)])
            prev = d
say(f"wrote data/processed/lista_mex_labels_por_anio.csv ({cat.num_rows} rows, "
    f"{len(avail)} codes) - full per-vintage label history")

# ============================================================ STEP 3 YEAR KEY
say(); say("=" * 78); say("STEP 3 - HANDLE THE YEAR KEY (file year -> occurrence year)"); say("=" * 78)
ao = joined["ANIO_OCUR"].to_pylist()

# 3a
say(); say("3a. ANIO_OCUR == 9999 by source-file year (kept; year label -> 'desconocido'):")
n9999 = collections.Counter(fy for fy, a in zip(joined["anio_archivo"].to_pylist(), ao) if a == 9999)
for y in YEARS:
    say(f"    {y}: {n9999[y]:>5}")
tot9999 = sum(n9999.values())
say(f"    total: {tot9999}")
anio_ocur = pa.array(["desconocido" if a == 9999 else str(a) for a in ao], pa.string())
joined = joined.append_column("anio_ocur", anio_ocur)

# 3b
say(); say("3b. registration-lag side table: source-file year x occurrence year -> CSV")
lag = collections.Counter(zip(joined["anio_archivo"].to_pylist(), anio_ocur.to_pylist()))
with open(f"{OUTDIR}/defunciones_rezago_registro.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["anio_archivo", "anio_ocurrencia", "defunciones"])
    for k in sorted(lag, key=lambda k: (k[0], k[1])):
        w.writerow([k[0], k[1], lag[k]])
say(f"    wrote data/processed/defunciones_rezago_registro.csv ({len(lag)} rows)")

# 3c
say(); say("3c. share of each occurrence year registered in a LATER file year (expect ~2%):")
occ_tot, occ_late = collections.Counter(), collections.Counter()
for (fy, oy), c in lag.items():
    if oy == "desconocido":
        continue
    occ_tot[oy] += c
    if fy > int(oy):
        occ_late[oy] += c
say(f"    {'occ_year':>8} {'deaths':>12} {'reg_later':>12} {'share':>8}")
lag_rows = []
for oy in sorted(occ_tot, key=lambda s: int(s)):
    if int(oy) < 2005:
        continue
    sh = occ_late[oy] / occ_tot[oy] if occ_tot[oy] else 0.0
    lag_rows.append((oy, occ_tot[oy], occ_late[oy], sh))
    say(f"    {oy:>8} {occ_tot[oy]:>12,} {occ_late[oy]:>12,} {sh:>7.2%}")
pre2005 = sum(c for oy, c in occ_tot.items() if int(oy) < 2005)
say(f"    occurrence years < 2005 (real): {pre2005:,} deaths - late registrations only, "
    f"NOT complete counts for those years.")

# ============================================================ STEP 4 AGGREGATE
say(); say("=" * 78); say("STEP 4 - AGGREGATE"); say("=" * 78)
lm  = joined["lm_key"].to_pylist();   sx  = joined["SEXO"].to_pylist()
ed  = joined["EDAD_AGRU"].to_pylist(); l1 = joined["LISTA1"].to_pylist()
cap = joined["CAPITULO"].to_pylist(); gr = joined["GRUPO"].to_pylist()
oy  = anio_ocur.to_pylist()
say("grain: anio_ocur | lista_mex | lista1 | capitulo | grupo | sexo | edad_agru")
say("lista_mex_desc = label from the OCCURRENCE year's catalog (D1-aligned), not one")
say("collapsed label. lista_mex_desc_anio_fuente records which catalog year it came from")
say("(differs from anio_ocur only when the occurrence year is outside the code's catalog")
say("coverage). Full per-vintage history is in lista_mex_labels_por_anio.csv.")
combos = collections.defaultdict(set)
for a, b, c2, d in zip(lm, l1, cap, gr):
    combos[a].add((b, c2, d))
n_multi = sum(1 for v in combos.values() if len(v) > 1)
say(f"NOTE: LISTA1/CAPITULO/GRUPO are NOT functionally determined by LISTA_MEX: {n_multi} codes "
    f"(mostly 'Z' residual codes) span >1 (LISTA1,CAPITULO,GRUPO) combo. They are therefore "
    f"kept IN the grain, not collapsed to one value. No row dropped, no value invented; the "
    f"count column still sums exactly (GATE 3).")

grp = collections.Counter()
for i in range(joined.num_rows):
    grp[(oy[i], lm[i], l1[i], cap[i], gr[i], sx[i], ed[i])] += 1
say(f"aggregate rows: {len(grp):,}")

rows = []
for (a_oy, a_lm, a_l1, a_cap, a_gr, a_sx, a_ed), cnt in grp.items():
    lbl, src_yr = resolve_label(a_oy, a_lm)
    rows.append(dict(
        anio_ocur=a_oy, lista_mex=a_lm,
        lista_mex_desc=lbl, lista_mex_desc_anio_fuente=src_yr,
        prefijo=re.match(r"^(\d+)", a_lm).group(1),
        lista1=a_l1, capitulo=a_cap, grupo=a_gr,
        sexo=a_sx, sexo_desc=SEXO_LABEL.get(a_sx),
        edad_agru=a_ed, edad_agru_desc=EDAD_AGRU_LABEL.get(a_ed),
        defunciones=cnt, provisional=(a_oy == "2024"),
    ))
def _is_fallback(r):
    return r["anio_ocur"] == "desconocido" or int(r["anio_ocur"]) != r["lista_mex_desc_anio_fuente"]
n_fallback = sum(1 for r in rows if _is_fallback(r))
n_inscope_fallback = sum(1 for r in rows if _is_fallback(r) and r["anio_ocur"] != "desconocido"
                         and 2005 <= int(r["anio_ocur"]) <= 2024)
say(f"aggregate rows whose label came from a fallback catalog year: {n_fallback:,} "
    f"({n_inscope_fallback} of them inside 2005-2024)")
drift_deaths = collections.Counter()
for r in rows:
    if r["lista_mex"] in label_changed:
        drift_deaths[r["lista_mex"]] += r["defunciones"]
drift_rows = sum(drift_deaths.values())
say(f"deaths under the {len(label_changed)} code(s) with any wording change: {drift_rows:,}")
# chronological drift description, one bullet per code
_dd = []
for k in sorted(label_changed):
    seq, prev = [], None
    for y in avail[k]:
        d = cat_label[(y, k)]
        if d != prev:
            seq.append(f"{y}: {d!r}")
            prev = d
    dn = drift_deaths[k]
    _dd.append(f"- `{k}` ({dn} death{'s' if dn != 1 else ''} total): " + "  →  ".join(seq))
drift_desc = "\n".join(_dd)
n_nulllabel = sum(1 for r in rows if r["lista_mex_desc"] is None)
n_nulll1 = sum(1 for r in rows if r["lista1"] is None)
say(f"aggregate rows with NULL cause label : {n_nulllabel}")
say(f"aggregate rows with NULL lista1      : {n_nulll1}  "
    f"(codes {sorted({r['lista_mex'] for r in rows if r['lista1'] is None})} - "
    f"no LISTA1 assigned by INEGI in the relevant catalog vintages; left NULL, not invented)")

# ------------------------------------------------------------ GATE 3
say(); say("-" * 78); say("GATE 3  sum(defunciones) + 'desconocido' == total rows of all 20 files"); say("-" * 78)
s_all  = sum(r["defunciones"] for r in rows)
s_desc = sum(r["defunciones"] for r in rows if r["anio_ocur"] == "desconocido")
s_src  = sum(src[y] for y in YEARS)
say(f"sum(defunciones), dated year rows : {s_all - s_desc:,}")
say(f"sum(defunciones), 'desconocido'   : {s_desc:,}")
say(f"sum(defunciones), total           : {s_all:,}")
say(f"total rows, 20 source files       : {s_src:,}")
if s_all != s_src:
    say("GATE 3 FAIL: STOP."); sys.exit(1)
say("GATE 3 result: exact match.")

# ============================================================ STEP 5 POPULATION
say(); say("=" * 78); say("STEP 5 - ADD POPULATION"); say("=" * 78)
pop = pq.read_table(CONAPO)
say("5a. CONAPO file: data/processed/poblacion_entidades.parquet")
say(f"    columns  : {[(f.name, str(f.type)) for f in pop.schema]}")
say(f"    row count: {pop.num_rows:,}")
say(f"    structure: {len(pc.unique(pop['cve_entidad']))} entidades x "
    f"{len(pc.unique(pop['anio']))} years ({pc.min(pop['anio']).as_py()}-{pc.max(pop['anio']).as_py()}) x "
    f"{len(pc.unique(pop['edad']))} single-year ages ({pc.min(pop['edad']).as_py()}-{pc.max(pop['edad']).as_py()}) x "
    f"{len(pc.unique(pop['sexo']))} sexes {pc.unique(pop['sexo']).to_pylist()}")
say("    supports (a) year only, (b) year+sex, AND (c) year+sex+age group.")
say("    -> joining at (c), the finest grain. National = sum of the 32 entidades;")
say("       single-year ages are folded into EDAD_AGRU groups via the crosswalk.")

# 5b crosswalk
say(); say("5b. EDAD_AGRU <-> CONAPO age crosswalk -> CSV")
unmapped = []
with open(f"{OUTDIR}/crosswalk_edad_agru_conapo.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["edad_agru", "edad_agru_desc", "conapo_edades", "estatus", "nota"])
    for k in sorted(EDAD_AGRU_TO_CONAPO):
        ages = EDAD_AGRU_TO_CONAPO[k]
        if ages is None:
            unmapped.append(k)
            nota = ("Edad no especificada: no hay denominador." if k == "30"
                    else "CONAPO llega solo a 109 anios; sin poblacion para 110+.")
            w.writerow([k, EDAD_AGRU_LABEL[k], "", "SIN MAPEO", nota])
        else:
            rng = str(ages[0]) if len(ages) == 1 else f"{ages[0]}-{ages[-1]}"
            w.writerow([k, EDAD_AGRU_LABEL[k], rng, "OK", ""])
say("    wrote data/processed/crosswalk_edad_agru_conapo.csv")
say("    01-26 map cleanly to single-year ages 0 .. 105-109.")
say(f"    UNMAPPED (rate left NULL): {unmapped}  -- 27/28/29 = ages 110+ (CONAPO max 109); "
    f"30 = age not stated.  SEXO=9 also has no CONAPO denominator -> rate NULL.")

# 5c national pop by (anio, sexo_conapo, edad_agru)
age2grp = {a: g for g, ags in EDAD_AGRU_TO_CONAPO.items() if ags for a in ags}
popnat = collections.Counter()
for a, s, e, n in zip(pop["anio"].to_pylist(), pop["sexo"].to_pylist(),
                      pop["edad"].to_pylist(), pop["poblacion"].to_pylist()):
    popnat[(a, s, age2grp[e])] += n
say(); say(f"5c. national population table: {len(popnat):,} (anio, sexo, edad_agru) cells")

# 5d
def denom(a_oy, a_sx, a_ed):
    if a_oy == "desconocido":
        return None
    yr = int(a_oy)
    s = SEXO_TO_CONAPO.get(a_sx)
    if s is None or EDAD_AGRU_TO_CONAPO.get(a_ed) is None:
        return None
    return popnat.get((yr, s, a_ed))

for r in rows:
    p = denom(r["anio_ocur"], r["sexo"], r["edad_agru"])
    r["poblacion"] = p
    r["tasa_100k"] = (100000.0 * r["defunciones"] / p) if p else None

# ------------------------------------------------------------ GATE 4
say(); say("-" * 78); say("GATE 4  population present for all 20 target years 2005-2024"); say("-" * 78)
say(f"{'year':>6} {'poblacion_total':>16}   (national, both sexes, mapped groups 01-26)")
ok4 = True
g4 = []
for y in YEARS:
    tp = sum(v for (a, s, g), v in popnat.items() if a == y)
    g4.append((y, tp))
    ok4 &= (90_000_000 < tp < 160_000_000)
    say(f"{y:>6} {tp:>16,}")
say("eyeball: ~106M (2005) -> ~132M (2024). CONAPO 'Proyecciones 2020-2070' rev. 2023,")
say("mid-year; ~3% above older census-based guesses (103M / 128M) because rev. 2023")
say("revised the series upward.")
# every in-scope (year, sex 1/2, group 01-26) death row must have a denominator
holes = [r for r in rows if r["poblacion"] is None and r["anio_ocur"] not in ("desconocido",)
         and 2005 <= int(r["anio_ocur"]) <= 2024 and r["sexo"] in (1, 2)
         and r["edad_agru"] not in ("27", "28", "29", "30")]
say(f"in-scope death rows missing a denominator (must be 0): {len(holes)}")
if not ok4 or holes:
    say("GATE 4 FAIL: STOP."); sys.exit(1)
say("GATE 4 result: population present and plausible for all 20 years.")

# ============================================================ STEP 6 OUTPUT
say(); say("=" * 78); say("STEP 6 - OUTPUT"); say("=" * 78)
schema = pa.schema([
    ("anio_ocur", pa.string()), ("lista_mex", pa.string()), ("lista_mex_desc", pa.string()),
    ("lista_mex_desc_anio_fuente", pa.int16()),
    ("prefijo", pa.string()), ("lista1", pa.string()), ("capitulo", pa.int16()),
    ("grupo", pa.int16()), ("sexo", pa.int8()), ("sexo_desc", pa.string()),
    ("edad_agru", pa.string()), ("edad_agru_desc", pa.string()),
    ("defunciones", pa.int64()), ("provisional", pa.bool_()),
    ("poblacion", pa.int64()), ("tasa_100k", pa.float64()),
])
agg = pa.table([pa.array([r[f.name] for r in rows], f.type) for f in schema], schema=schema)
agg = agg.sort_by([("anio_ocur", "ascending"), ("lista_mex", "ascending"), ("sexo", "ascending"),
                   ("edad_agru", "ascending"), ("capitulo", "ascending"), ("grupo", "ascending")])
pq.write_table(agg, f"{OUTDIR}/defunciones_agregado_2005_2024.parquet", compression="zstd")
n_nullrate = pc.sum(pc.is_null(agg["tasa_100k"])).as_py()
say(f"wrote data/processed/defunciones_agregado_2005_2024.parquet")
say(f"  rows={agg.num_rows:,}  sum(defunciones)={pc.sum(agg['defunciones']).as_py():,}")
say(f"  NULL tasa_100k rows: {n_nullrate:,}")

# ---- the note ----
today = datetime.date.today().isoformat()
crude = {y: (occ_tot[str(y)], tp) for (y, tp) in g4}
note = f"""# Aggregate table — deaths by cause, sex, age group (occurrence years 2005–2024)

Built by `scripts/build_aggregate.py` on {today}. Row-per-death → counts + crude
rates. No inference, no analysis, no age-standardization.

## Files

| file | what |
|---|---|
| `defunciones_agregado_2005_2024.parquet` | the aggregate table ({agg.num_rows:,} rows) |
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
`lista_mex` — {n_multi} codes (mostly the `…Z` residual codes) span more than one
(`lista1`,`capitulo`,`grupo`) combination — so they sit **in the grain**, not as
carried single values. Nothing was collapsed, dropped, or invented; the count
column still reconciles exactly (Gate 3).

`prefijo` is the numeric stem of `lista_mex` (`27Z` → `27`), for grouping
related codes later.

## Year convention (D1)

The year key is **year of occurrence** (`ANIO_OCUR`), not registration.

- `ANIO_OCUR == 9999` (sentinel for unknown) → `anio_ocur = 'desconocido'`.
  9999 never becomes a number. **{tot9999}** rows, by source-file year:
  {", ".join(f"{y}:{n9999[y]}" for y in YEARS)}.
- `provisional = TRUE` for occurrence year **2024** only. Deaths that occurred in
  2024 but were registered in 2025 are not in this data yet, so 2024 is
  undercounted by roughly 2% (see the lag table — every complete year shows
  ~2.0–2.5% of its deaths registered in a later year; 2024 shows 0%).
- Occurrence years **before 2005** ({pre2005:,} rows) and `desconocido` are kept
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
**{n_fallback:,}** rows use such a fallback, and **every one is an occurrence
year before 2005 or `desconocido`** ({n_inscope_fallback} rows inside the target
range 2005–2024 use a fallback) — so within scope the label is always the code's
own occurrence-year wording.

Wording drift across the 20 vintages: **{len(label_changed)}** code(s).
{drift_desc}
The full per-vintage label history for all {len(avail)} catalog codes is in
`lista_mex_labels_por_anio.csv` (column `cambio_vs_anio_previo`) — a string diff
catches renamed codes, not a code silently reused for a different concept, so
check that file directly rather than trusting this count.

`lista1` is NULL for **{n_nulll1}** aggregate rows: codes
{sorted({r['lista_mex'] for r in rows if r['lista1'] is None})} (COVID-19 and the
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

`tasa_100k` is NULL for **{n_nullrate:,}** rows total (`anio_ocur='desconocido'`,
`sexo=9`, `edad_agru` 27/28/29/30, or occurrence year before 1970).

## Gate results

| gate | result |
|---|---|
| **1** catalog union | **8366** rows (= 8365 + the documented 06T patch to the 2020 catalog), **20** distinct years. Per-year: 417 (2005–2015), 418 (2016–2019), **419 (2020)**, 422 (2021–2024). |
| **2** per-year validity join | joined rows == source rows for **every** year; **diff 0** throughout; **0** unmatched codes. |
| **3** count reconciliation | sum(defunciones) = **{s_all:,}** = total rows of the 20 source files ({s_src:,}). Dated {s_all - s_desc:,} + desconocido {s_desc:,}. |
| **4** population coverage | present & plausible for all 20 years; **0** in-scope death rows missing a denominator. ~106.4M (2005) → ~132.3M (2024). |

### Gate 2 detail (year: source = joined, diff)
{chr(10).join(f"- {y}: {src[y]:,} = {jnd[y]:,}, diff 0" for y in YEARS)}

### Gate 4 detail (occurrence-year totals & crude rate, both sexes / all ages)
| occ year | deaths | national pop | crude /100k |
|---|---|---|---|
{chr(10).join(f"| {y} | {crude[y][0]:,} | {crude[y][1]:,} | {1e5*crude[y][0]/crude[y][1]:.1f} |" for y in YEARS)}

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
{_buf.getvalue().rstrip()}
```
"""
open(f"{OUTDIR}/DEFUNCIONES_AGREGADO.md", "w").write(note)
print("wrote data/processed/DEFUNCIONES_AGREGADO.md")
print("\nDONE.")
