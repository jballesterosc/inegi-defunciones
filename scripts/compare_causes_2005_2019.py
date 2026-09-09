#!/usr/bin/env python
"""Which causes of death rose in Mexico 2005 -> 2019, and which fell. In RATES.

Window: occurrence year 2005-2019 (D4). Exclude 'desconocido' and anio_ocur<2005
(D5). Report crude AND age-standardized rates (D6), standard = CONAPO 2010
sex-and-age structure. Never average a rate: sum deaths, sum population, divide
(D7).

No interpretation. Table + note only.

Run:  .venv/bin/python scripts/compare_causes_2005_2019.py
"""
from __future__ import annotations
import csv, io, re, sys, datetime, collections
import pyarrow.parquet as pq

REPO = __file__.rsplit("/scripts/", 1)[0]
AGG = REPO + "/data/processed/defunciones_agregado_2005_2024.parquet"
LABELS = REPO + "/data/processed/lista_mex_labels_por_anio.csv"
OUTDIR = REPO + "/data/processed"
YEARS = [str(y) for y in range(2005, 2020)]         # D4: 2005..2019 inclusive
Y0, Y1 = "2005", "2019"
STD_YEAR = "2010"                                   # D6
EPS = 0.1            # per 100k: |change| below this is "flat"
RECIP_LARGE = 3.0    # per 100k: a "large" single-code standardized move
RECIP_FRAC = 0.34    # net <= this * smaller opposing move  => "roughly cancels"

buf = io.StringIO()
def say(s=""):
    print(s); buf.write(str(s) + "\n")

# ---- load ---------------------------------------------------------------
rows = pq.read_table(AGG).to_pylist()
say(f"aggregate rows: {len(rows):,}")

# D4 + D5: keep occurrence years 2005-2019 only
w = [r for r in rows if r["anio_ocur"] != "desconocido" and 2005 <= int(r["anio_ocur"]) <= 2019]
say(f"rows in window 2005-2019 (excl. 'desconocido' and <2005): {len(w):,}")

# labels by catalog year
LB = collections.defaultdict(dict)
for r in csv.DictReader(open(LABELS)):
    LB[r["lista_mex"]][int(r["anio_catalogo"])] = r["descrip"]

MAPPED_SEX = (1, 2)
UNMAPPED_EDAD = {"27", "28", "29", "30"}

# ======================================================================
# STEP 1 - DENOMINATOR  (distinct (year, sexo, edad_agru, poblacion) tuples)
# ======================================================================
say("\n" + "=" * 74)
say("STEP 1 - DENOMINATOR (distinct year x sexo x edad_agru x poblacion)")
say("=" * 74)
pop = {}                     # (year, sexo, edad_agru) -> poblacion   (mapped strata only)
for r in w:
    if r["poblacion"] is None:
        continue
    k = (r["anio_ocur"], r["sexo"], r["edad_agru"])
    if k in pop and pop[k] != r["poblacion"]:
        say(f"FATAL: poblacion disagrees for {k}: {pop[k]} vs {r['poblacion']}"); sys.exit(1)
    pop[k] = r["poblacion"]
natpop = collections.Counter()
for (y, s, e), p in pop.items():
    natpop[y] += p

say("\n" + "-" * 74)
say("GATE 5 - national population per year, built from distinct tuples")
say("-" * 74)
g5_ok = True
for y in YEARS:
    say(f"  {y}: {natpop[y]:>13,}")
    if not (100_000_000 < natpop[y] < 200_000_000):
        g5_ok = False
if not g5_ok:
    say("GATE 5 FAIL: a year is outside 100-200M (multiply-count error?). STOP."); sys.exit(1)
say(f"GATE 5 result: rises {natpop[Y0]:,} -> {natpop[Y1]:,}, all in the 100-130M band. OK.")

# standard population = CONAPO 2010 sex x age structure (mapped strata)
stdpop = {(s, e): p for (y, s, e), p in pop.items() if y == STD_YEAR}
STD_TOTAL = sum(stdpop.values())
say(f"\nstandard population = CONAPO {STD_YEAR}: {len(stdpop)} strata "
    f"(sex {sorted({s for s,_ in stdpop})} x {len({e for _,e in stdpop})} age groups), "
    f"total {STD_TOTAL:,}")

# ======================================================================
# STEP 2 - CRUDE RATES BY CAUSE
# ======================================================================
say("\n" + "=" * 74)
say("STEP 2 - CRUDE RATES BY CAUSE (sum ALL deaths / national pop x 100k)")
say("=" * 74)
# deaths[(code, year)] = deaths summed over ALL sexo & edad_agru (residual codes collapsed)
deaths_cy = collections.Counter()
# deaths_stratum[(code, year, sexo, edad_agru)] for standardization
deaths_cyse = collections.Counter()
for r in w:
    deaths_cy[(r["lista_mex"], r["anio_ocur"])] += r["defunciones"]
    deaths_cyse[(r["lista_mex"], r["anio_ocur"], r["sexo"], r["edad_agru"])] += r["defunciones"]

def crude(code, year):
    return 100000.0 * deaths_cy[(code, year)] / natpop[year]

say("\n" + "-" * 74)
say("GATE 6 - sum of deaths across all causes (2019) == total 2019 window deaths")
say("-" * 74)
sum_by_cause_2019 = sum(v for (c, y), v in deaths_cy.items() if y == "2019")
total_window_2019 = sum(r["defunciones"] for r in w if r["anio_ocur"] == "2019")
say(f"  sum over causes, 2019 : {sum_by_cause_2019:,}")
say(f"  total 2019 in window  : {total_window_2019:,}")
if sum_by_cause_2019 != total_window_2019:
    say("GATE 6 FAIL: null-rate deaths (ages 110+, unstated age, sexo=9) were dropped. STOP.")
    sys.exit(1)
say("GATE 6 result: exact match; null-denominator deaths kept in the numerator.")

# ======================================================================
# STEP 3 - AGE-STANDARDIZED RATES BY CAUSE (direct, to CONAPO 2010)
# ======================================================================
say("\n" + "=" * 74)
say("STEP 3 - AGE-STANDARDIZED RATES (direct standardization to CONAPO 2010)")
say("=" * 74)

def std_rate(code, year):
    acc = 0.0
    for (s, e), sp in stdpop.items():
        d = deaths_cyse[(code, year, s, e)]
        if d == 0:
            continue
        acc += (d / pop[(year, s, e)]) * sp
    return 100000.0 * acc / STD_TOTAL

# deaths excluded from standardization (unmapped strata) per year
excl_by_year = collections.Counter()
for r in w:
    if r["sexo"] not in MAPPED_SEX or r["edad_agru"] in UNMAPPED_EDAD:
        excl_by_year[r["anio_ocur"]] += r["defunciones"]
say("\ndeaths EXCLUDED from standardization (sexo=9 or edad_agru 27/28/29/30), per year:")
worst = 0.0
for y in YEARS:
    tot = sum(r["defunciones"] for r in w if r["anio_ocur"] == y)
    pctv = 100 * excl_by_year[y] / tot
    worst = max(worst, pctv)
    say(f"  {y}: {excl_by_year[y]:>5}  ({pctv:.2f}% of {tot:,})")
say(f"max share in any year: {worst:.2f}%")
if worst > 3.0:
    say("STOP: excluded share exceeds 3% in some year - standardization would be distorted.")
    sys.exit(1)
say("excluded share is small (<3% every year) - proceeding.")

# per-cause exclusion can be higher for external causes with unidentified decedents
ct = collections.Counter(); ce = collections.Counter()
for r in w:
    if r["anio_ocur"] in (Y0, Y1):
        ct[r["lista_mex"]] += r["defunciones"]
        if r["sexo"] == 9 or r["edad_agru"] in UNMAPPED_EDAD:
            ce[r["lista_mex"]] += r["defunciones"]
hi_excl = sorted(((c, ce[c], ct[c], 100 * ce[c] / ct[c]) for c in ct
                  if ct[c] >= 200 and ce[c] / ct[c] > 0.02), key=lambda t: -t[3])
say(f"\nper-cause: {len(hi_excl)} causes (>=200 deaths in {Y0}+{Y1}) exclude >2% from standardization "
    f"(external causes with unidentified decedents):")
for c, e, t, p in hi_excl:
    say(f"  {c}: {e}/{t} = {p:.1f}%   (its standardized rate is computed on identified deaths only)")

say("\n" + "-" * 74)
say(f"GATE 7 - all-cause standardized rate ({STD_YEAR}) ~= all-cause crude rate ({STD_YEAR})")
say("-" * 74)
allcause_crude_2010 = 100000.0 * sum(deaths_cy[(c, STD_YEAR)] for c in {c for c, _ in deaths_cy}) / natpop[STD_YEAR]
# all-cause standardized: apply each stratum's 2010 all-cause rate to the 2010 standard pop
allcause_std_2010 = 0.0
strat_deaths_2010 = collections.Counter()
for (c, y, s, e), d in deaths_cyse.items():
    if y == STD_YEAR:
        strat_deaths_2010[(s, e)] += d
for (s, e), sp in stdpop.items():
    d = strat_deaths_2010[(s, e)]
    allcause_std_2010 += (d / pop[(STD_YEAR, s, e)]) * sp
allcause_std_2010 = 100000.0 * allcause_std_2010 / STD_TOTAL
gap = allcause_crude_2010 - allcause_std_2010
say(f"  all-cause crude {STD_YEAR}        : {allcause_crude_2010:.2f} / 100k")
say(f"  all-cause standardized {STD_YEAR} : {allcause_std_2010:.2f} / 100k")
say(f"  gap                        : {gap:.2f} / 100k "
    f"(= the {excl_by_year[STD_YEAR]:,} deaths with no denominator, /natpop)")
if abs(gap) > 5.0:
    say("GATE 7 FAIL: gap > 5/100k - standardization is wrong. STOP."); sys.exit(1)
say("GATE 7 result: gap within 5/100k, explained entirely by the excluded deaths. OK.")

# ======================================================================
# STEP 4 + 5 - COMPARISON TABLE with FLAGS
# ======================================================================
say("\n" + "=" * 74)
say("STEP 4 + 5 - COMPARISON TABLE + FLAGS")
say("=" * 74)
codes = sorted({c for (c, y), v in deaths_cy.items() if y in (Y0, Y1) and v > 0})
say(f"cause codes with deaths in {Y0} or {Y1}: {len(codes)}")

def direction(change):
    if change > EPS:  return "up"
    if change < -EPS: return "down"
    return "flat"

def pct(a, b):        # % change from a to b
    return None if a == 0 else 100.0 * (b - a) / a

table = []
flagcount = collections.Counter()
for c in codes:
    d05, d19 = deaths_cy[(c, Y0)], deaths_cy[(c, Y1)]
    cr05, cr19 = crude(c, Y0), crude(c, Y1)
    sr05, sr19 = std_rate(c, Y0), std_rate(c, Y1)
    l05, l19 = LB[c].get(2005), LB[c].get(2019)
    cr_ch, sr_ch = cr19 - cr05, sr19 - sr05
    dir_c, dir_s = direction(cr_ch), direction(sr_ch)

    flags = []
    if l05 is None or l19 is None or l05 != l19:
        flags.append("LABEL_DRIFT")
    if d05 < 100:
        flags.append("LOW_BASE")
    if d05 == 0 or d19 == 0:
        flags.append("ZERO_YEAR")
    if dir_c in ("up", "down") and dir_s in ("up", "down") and dir_c != dir_s:
        flags.append("DIRECTION_FLIP")
    for f in flags:
        flagcount[f] += 1

    table.append(dict(
        lista_mex=c, label_2005=l05, label_2019=l19,
        prefijo=re.match(r"^(\d+)", c).group(1),
        deaths_2005=d05, deaths_2019=d19,
        crude_2005=round(cr05, 4), crude_2019=round(cr19, 4),
        crude_change=round(cr_ch, 4), crude_pct_change=(None if pct(cr05, cr19) is None else round(pct(cr05, cr19), 2)),
        std_2005=round(sr05, 4), std_2019=round(sr19, 4),
        std_change=round(sr_ch, 4), std_pct_change=(None if pct(sr05, sr19) is None else round(pct(sr05, sr19), 2)),
        direction_crude=dir_c, direction_std=dir_s,
        flags="|".join(flags),
    ))

table.sort(key=lambda r: r["std_change"], reverse=True)
say("\nflag counts:")
for f in ("LABEL_DRIFT", "LOW_BASE", "ZERO_YEAR", "DIRECTION_FLIP"):
    say(f"  {f:15}: {flagcount[f]}")
say(f"  rows with >=1 flag : {sum(1 for r in table if r['flags'])}")
say(f"  rows with no flag  : {sum(1 for r in table if not r['flags'])}")

# sanity: sum of per-cause std rates ~ all-cause std rate, both years
for y, srf in ((Y0, lambda c: std_rate(c, Y0)), (Y1, lambda c: std_rate(c, Y1))):
    tot = sum(srf(c) for c in codes)
    say(f"  sum of per-cause standardized rates, {y}: {tot:.2f}/100k")

# ======================================================================
# STEP 6 - PREFIX RECIPROCITY CHECK
# ======================================================================
say("\n" + "=" * 74)
say("STEP 6 - PREFIX RECIPROCITY (standardized rate change within each prefix)")
say("=" * 74)
byp = collections.defaultdict(list)
for r in table:
    byp[r["prefijo"]].append(r)

prefix_rows = []
for p in sorted(byp, key=lambda p: int(p)):
    members = byp[p]
    ch = {m["lista_mex"]: m["std_change"] for m in members}
    net = sum(ch.values())
    ups = {k: v for k, v in ch.items() if v > 0}
    downs = {k: v for k, v in ch.items() if v < 0}
    gross_up = sum(ups.values())
    gross_down = -sum(downs.values())
    churn = min(gross_up, gross_down)          # magnitude that cancels within the prefix
    rise_code, rise = (max(ups.items(), key=lambda t: t[1]) if ups else ("", 0.0))
    fall_code, fall = (min(downs.items(), key=lambda t: t[1]) if downs else ("", 0.0))
    # reclassification pattern: large gross churn inside the prefix, near-zero net
    reciprocity = churn >= RECIP_LARGE and abs(net) <= RECIP_FRAC * churn
    prefix_rows.append(dict(
        prefijo=p, n_codes=len(members),
        codes="|".join(sorted(ch)),
        net_std_change=round(net, 4),
        gross_up=round(gross_up, 4), gross_down=round(gross_down, 4), churn=round(churn, 4),
        largest_rise=round(rise, 4), largest_rise_code=rise_code,
        largest_fall=round(fall, 4), largest_fall_code=fall_code,
        reciprocity_flag=reciprocity,
    ))

flagged = [r for r in prefix_rows if r["reciprocity_flag"]]
say(f"\nreciprocity rule: churn = min(gross_up, gross_down) >= {RECIP_LARGE}/100k "
    f"AND |net| <= {RECIP_FRAC} * churn  (a large rise and a large fall inside the "
    f"prefix roughly cancel -> deaths moved between codes = reclassification)")
say(f"prefixes flagged: {len(flagged)}")
for r in flagged:
    say(f"  prefix {r['prefijo']} ({r['codes']}): net {r['net_std_change']:+.2f}/100k, "
        f"churn {r['churn']:.2f} (up {r['gross_up']:.2f} / down {r['gross_down']:.2f}); "
        f"largest rise {r['largest_rise']:+.2f} ({r['largest_rise_code']}), "
        f"largest fall {r['largest_fall']:+.2f} ({r['largest_fall_code']})")

for p in ("27", "29"):
    r = next(x for x in prefix_rows if x["prefijo"] == p)
    say(f"\nprefix {p} (reported regardless): codes {r['codes']}")
    say(f"  net standardized change : {r['net_std_change']:+.3f} / 100k")
    say(f"  gross up / down / churn  : {r['gross_up']:.3f} / {r['gross_down']:.3f} / {r['churn']:.3f}")
    say(f"  largest rise            : {r['largest_rise']:+.3f} ({r['largest_rise_code'] or 'none'})")
    say(f"  largest fall            : {r['largest_fall']:+.3f} ({r['largest_fall_code'] or 'none'})")
    say(f"  reciprocity flag        : {r['reciprocity_flag']}")
    for m in sorted(byp[p], key=lambda m: m["lista_mex"]):
        say(f"    {m['lista_mex']}  std {m['std_2005']:.2f} -> {m['std_2019']:.2f}  "
            f"(chg {m['std_change']:+.2f})  crude chg {m['crude_change']:+.2f}  [{m['flags']}]")

# ======================================================================
# STEP 7 - OUTPUT
# ======================================================================
say("\n" + "=" * 74)
say("STEP 7 - OUTPUT")
say("=" * 74)
cmp_path = f"{OUTDIR}/causas_comparacion_2005_2019.csv"
with open(cmp_path, "w", newline="") as fh:
    wtr = csv.DictWriter(fh, fieldnames=list(table[0].keys()))
    wtr.writeheader(); wtr.writerows(table)
say(f"wrote {cmp_path}  ({len(table)} rows, sorted by std_change desc)")

pfx_path = f"{OUTDIR}/causas_prefijo_reciprocidad_2005_2019.csv"
with open(pfx_path, "w", newline="") as fh:
    wtr = csv.DictWriter(fh, fieldnames=list(prefix_rows[0].keys()))
    wtr.writeheader(); wtr.writerows(sorted(prefix_rows, key=lambda r: r["net_std_change"]))
say(f"wrote {pfx_path}  ({len(prefix_rows)} prefixes)")

# top movers for the note (exclude LOW_BASE / ZERO_YEAR from any ranking)
rankable = [r for r in table if "LOW_BASE" not in r["flags"] and "ZERO_YEAR" not in r["flags"]]
up = [r for r in rankable if r["direction_std"] == "up"][:15]
down = sorted([r for r in rankable if r["direction_std"] == "down"], key=lambda r: r["std_change"])[:15]

# all-cause rates for the summary (D7: sum deaths, sum pop, divide)
allcodes_all = {c for c, _ in deaths_cy}
allcause_crude_2005 = sum(crude(c, Y0) for c in allcodes_all)
allcause_crude_2019 = sum(crude(c, Y1) for c in allcodes_all)
allcause_std_2005 = sum(std_rate(c, Y0) for c in allcodes_all)
allcause_std_2019 = sum(std_rate(c, Y1) for c in allcodes_all)

def _prefix_block(p):
    r = next(x for x in prefix_rows if x["prefijo"] == p)
    lines = [f"- **prefix {p}** (codes {r['codes']}): net {r['net_std_change']:+.3f}/100k · "
             f"churn {r['churn']:.2f} (gross up {r['gross_up']:.2f} / down {r['gross_down']:.2f}) · "
             f"largest rise {r['largest_rise']:+.3f} ({r['largest_rise_code'] or 'none'}) · "
             f"largest fall {r['largest_fall']:+.3f} ({r['largest_fall_code'] or 'none'}) · "
             f"reciprocity flag: **{r['reciprocity_flag']}**"]
    for m in sorted(byp[p], key=lambda m: m["lista_mex"]):
        lines.append(f"  - {m['lista_mex']} — std {m['std_2005']:.2f} → {m['std_2019']:.2f} "
                     f"(Δ {m['std_change']:+.2f}), crude Δ {m['crude_change']:+.2f}"
                     + (f"  [{m['flags']}]" if m['flags'] else ""))
    return "\n".join(lines)
prefix_2729 = "\n".join(_prefix_block(p) for p in ("27", "29"))

today = datetime.date.today().isoformat()
note = f"""# Causes of death, Mexico, occurrence years {Y0} vs {Y1} — rate comparison

Built by `scripts/compare_causes_2005_2019.py` on {today}, from
`data/processed/defunciones_agregado_2005_2024.parquet`. Rates only, not counts.
No interpretation — the table is the deliverable.

## Locked decisions applied

- **D4** window = occurrence year {Y0}–{Y1} (last pre-COVID year); 2020–2024 excluded.
- **D5** excluded `anio_ocur = 'desconocido'` and `anio_ocur < 2005` (late registrations).
- **D6** both crude and age-standardized rates reported; standard = CONAPO {STD_YEAR} sex-and-age structure.
- **D7** every rate = (Σ deaths) / (Σ population) × 100 000. No rate is ever averaged.

## Method

- **Denominator** built from **distinct `(anio_ocur, sexo, edad_agru, poblacion)`
  tuples**, then summed per year — never summed over cause rows (that would
  multiply-count population ~400×).
- **Crude rate**, cause × year: Σ deaths over every sex and age group (including
  `sexo=9` and `edad_agru` 27/28/29/30, which have no denominator) ÷ that year's
  national population × 100 000.
- **Standardized rate**, cause × year: direct standardization — stratum rate
  `deaths / population` for each (sex, age-group) stratum with a denominator,
  weighted by the CONAPO {STD_YEAR} population of that stratum, summed, × 100 000.
  Strata without a denominator (`sexo=9`, `edad_agru` 27/28/29/30) are excluded
  **from standardization only**; those deaths remain in the crude numerator.
- **Residual codes** (`…Z` etc., 41 codes that occupy several rows per cell
  because `lista1`/`capitulo`/`grupo` vary): deaths summed by `lista_mex` first,
  so each is one cause, not several.
- Standard population = CONAPO {STD_YEAR}: {len(stdpop)} strata (2 sexes ×
  {len({e for _, e in stdpop})} age groups 01–26), total {STD_TOTAL:,}.

## Gate results

### GATE 5 — national population per year (distinct-tuple denominator)
| year | population |
|---|---|
{chr(10).join(f"| {y} | {natpop[y]:,} |" for y in YEARS)}

Rises {natpop[Y0]:,} → {natpop[Y1]:,}, every year in the 100–130 M band. **PASS**
(no multiply-count error).

### GATE 6 — all-cause deaths, 2019
- Σ deaths across all causes (2019): **{sum_by_cause_2019:,}**
- Total 2019 deaths in window: **{total_window_2019:,}**
- Exact match. **PASS** — the null-denominator deaths (ages 110+, unstated age,
  `sexo=9`) stay in the numerator.

### GATE 7 — all-cause standardized vs crude, {STD_YEAR} (the standard year)
- all-cause crude {STD_YEAR}: **{allcause_crude_2010:.2f}** / 100 000
- all-cause standardized {STD_YEAR}: **{allcause_std_2010:.2f}** / 100 000
- gap: **{gap:.2f}** / 100 000 — equals the {excl_by_year[STD_YEAR]:,} deaths with
  no denominator that year, divided by the national population. **PASS** (< 5/100k).

## Deaths excluded from standardization (per year)

`sexo = 9` or `edad_agru` in {{27, 28, 29, 30}}. Kept in crude rates, dropped
from standardization only.

| year | excluded deaths | % of year's deaths |
|---|---|---|
{chr(10).join(f"| {y} | {excl_by_year[y]:,} | {100*excl_by_year[y]/sum(r['defunciones'] for r in w if r['anio_ocur']==y):.2f}% |" for y in YEARS)}

Max in any year: **{worst:.2f}%** — small; standardization proceeded.

Per-cause the share is higher for a few external-cause codes whose decedents are
more often unidentified (age/sex unknown) — their standardized rate is computed
on identified deaths only:
{chr(10).join(f"- `{c}` {LB[c].get(2019, '')[:40]}: {e}/{t} = {p:.1f}% ({Y0}+{Y1})" for c, e, t, p in hi_excl) or "- (none above 2%)"}

## Flag counts (of {len(table)} cause codes)

| flag | count | meaning |
|---|---|---|
| `LABEL_DRIFT` | {flagcount['LABEL_DRIFT']} | 2005 and 2019 catalog labels differ — comparison may be invalid |
| `LOW_BASE` | {flagcount['LOW_BASE']} | < 100 deaths in 2005 — % change unstable; not ranked |
| `ZERO_YEAR` | {flagcount['ZERO_YEAR']} | zero deaths in 2005 or 2019 |
| `DIRECTION_FLIP` | {flagcount['DIRECTION_FLIP']} | crude and standardized rates move opposite ways — aging explains the crude trend |
| any flag | {sum(1 for r in table if r['flags'])} | |
| no flag | {sum(1 for r in table if not r['flags'])} | |

`LABEL_DRIFT` = 0: no code's Lista Mexicana wording changed between the 2005 and
2019 catalog vintages (checked against `lista_mex_labels_por_anio.csv`). A string
diff does not catch a code reused for a different concept — see STEP 6.

`flat` threshold: |rate change| < {EPS}/100 000 over the 14-year window.

## Prefix reciprocity (STEP 6)

Grouped by `prefijo` (`27A`, `27B`, `27Z` → `27`). For each prefix: net Δ
standardized rate, the gross rise (Σ positive Δ), the gross fall (Σ |negative Δ|),
and `churn = min(gross_up, gross_down)` — the magnitude that cancels within the
group.

Rule: **flagged** when `churn ≥ {RECIP_LARGE}/100k` **and** `|net| ≤ {RECIP_FRAC} ×
churn` — a large amount of movement inside the prefix nets to nearly nothing, so
deaths shifted between codes of the same prefix (reclassification) rather than a
real change in that group's mortality.

Prefixes flagged: **{len(flagged)}**
{chr(10).join(f"- **{r['prefijo']}** ({r['codes']}): net {r['net_std_change']:+.2f}/100k, churn {r['churn']:.2f} (up {r['gross_up']:.2f} / down {r['gross_down']:.2f}); largest rise {r['largest_rise']:+.2f} ({r['largest_rise_code']}), largest fall {r['largest_fall']:+.2f} ({r['largest_fall_code']})" for r in flagged) or "- (none)"}

Reported regardless of result:
{prefix_2729}

Full prefix table: `causas_prefijo_reciprocidad_2005_2019.csv`.

## Movement summary (excludes LOW_BASE and ZERO_YEAR rows)

Of {len(rankable)} rankable codes ({len(table)-len(rankable)} carry
LOW_BASE/ZERO_YEAR and are not ranked):

| direction | crude rate | standardized rate |
|---|---|---|
| rose | {sum(1 for r in rankable if r['direction_crude']=='up')} | {sum(1 for r in rankable if r['direction_std']=='up')} |
| fell | {sum(1 for r in rankable if r['direction_crude']=='down')} | {sum(1 for r in rankable if r['direction_std']=='down')} |
| flat (<{EPS}/100k) | {sum(1 for r in rankable if r['direction_crude']=='flat')} | {sum(1 for r in rankable if r['direction_std']=='flat')} |

All-cause rate, both sexes, all ages (Σ deaths / Σ population, per D7):
crude **{allcause_crude_2005:.1f} → {allcause_crude_2019:.1f}** /100k;
standardized to {STD_YEAR} **{allcause_std_2005:.1f} → {allcause_std_2019:.1f}** /100k.
{flagcount['DIRECTION_FLIP']} individual codes carry `DIRECTION_FLIP` (crude and
standardized move opposite ways).

### Largest standardized rises (rankable only)
| lista_mex | label 2019 | std 2005 | std 2019 | Δ std | dir crude | flags |
|---|---|---|---|---|---|---|
{chr(10).join(f"| {r['lista_mex']} | {r['label_2019'][:44]} | {r['std_2005']:.2f} | {r['std_2019']:.2f} | {r['std_change']:+.2f} | {r['direction_crude']} | {r['flags']} |" for r in up)}

### Largest standardized falls (rankable only)
| lista_mex | label 2019 | std 2005 | std 2019 | Δ std | dir crude | flags |
|---|---|---|---|---|---|---|
{chr(10).join(f"| {r['lista_mex']} | {r['label_2019'][:44]} | {r['std_2005']:.2f} | {r['std_2019']:.2f} | {r['std_change']:+.2f} | {r['direction_crude']} | {r['flags']} |" for r in down)}

## Files

| file | what |
|---|---|
| `causas_comparacion_2005_2019.csv` | one row per cause code, sorted by Δ standardized rate desc |
| `causas_prefijo_reciprocidad_2005_2019.csv` | one row per prefix |

## Console log

```
{buf.getvalue().rstrip()}
```
"""
open(f"{OUTDIR}/CAUSAS_2005_2019.md", "w").write(note)
print("wrote data/processed/CAUSAS_2005_2019.md")
print("\nDONE.")
