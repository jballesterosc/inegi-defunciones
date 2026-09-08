"""Command-line interface for the INEGI EDR microdata scraper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import Catalog, refresh_catalog
from .pipeline import resolve_years, run

_FORMATS = {"parquet": ["parquet"], "csv": ["csv"], "both": ["parquet", "csv"]}


def _parse_years(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="inegi-defunciones",
        description=(
            "Download INEGI's Estadísticas de Defunciones Registradas (EDR) "
            "open microdata and convert it to Parquet/CSV."
        ),
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Output directory (default: ./data). Holds raw/, interim/, processed/.",
    )
    sub = p.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Download + extract + convert (default).")
    grp = run_p.add_mutually_exclusive_group()
    grp.add_argument("--years", type=_parse_years, metavar="LIST",
                     help='Explicit years, e.g. "2015,2018-2020".')
    run_p.add_argument("--start-year", type=int, help="First year (inclusive).")
    run_p.add_argument("--end-year", type=int, help="Last year (inclusive).")
    run_p.add_argument("--format", choices=_FORMATS, default="parquet",
                       help="Output format(s) for the converted tables (default: parquet).")
    run_p.add_argument("--download-only", action="store_true",
                       help="Fetch the zip archives but do not extract or convert.")
    run_p.add_argument("--drop-zip", action="store_true",
                       help="Delete each zip after it is processed.")
    run_p.add_argument("--refresh-catalog", action="store_true",
                       help="Resolve download URLs from INEGI's listing API, not the built-in map.")
    run_p.add_argument("--force", action="store_true",
                       help="Re-download / re-extract / re-convert even if outputs exist.")
    run_p.add_argument("--quiet", action="store_true", help="Suppress progress output.")

    cat_p = sub.add_parser("catalog", help="Show the known archives and year coverage.")
    cat_p.add_argument("--refresh", action="store_true",
                       help="Fetch the current list from INEGI instead of the built-in map.")

    return p


def _cmd_catalog(args: argparse.Namespace) -> int:
    catalog = refresh_catalog() if args.refresh else Catalog()
    years = catalog.available_years
    print(f"{len(catalog.archives)} archives, years {years[0]}-{years[-1]}\n")
    for a in catalog.archives:
        span = f"{a.years[0]}-{a.years[-1]}" if a.is_bundle else str(a.years[0])
        print(f"  {span:<11} {a.url}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    years = resolve_years(
        getattr(args, "start_year", None),
        getattr(args, "end_year", None),
        getattr(args, "years", None),
    )
    catalog = refresh_catalog() if args.refresh_catalog else Catalog()
    try:
        catalog.archives_for_years(years)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 2

    manifest = run(
        data_dir=args.data_dir,
        years=years,
        formats=_FORMATS[args.format],
        catalog=catalog,
        download_only=args.download_only,
        keep_zip=not args.drop_zip,
        force=args.force,
        quiet=args.quiet,
    )
    n_tables = len(manifest["tables"])
    total_rows = sum(t["rows"] for t in manifest["tables"])
    print(
        f"\nDone. {len(manifest['archives'])} archive(s), "
        f"{n_tables} year table(s), {total_rows:,} rows."
        f"\nOutputs in {args.data_dir / 'processed'}/"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"
    if command == "catalog":
        return _cmd_catalog(args)
    # default to `run`; fill defaults if invoked with no subcommand
    for attr, default in (
        ("years", None), ("start_year", None), ("end_year", None),
        ("format", "parquet"), ("download_only", False), ("drop_zip", False),
        ("refresh_catalog", False), ("force", False), ("quiet", False),
    ):
        if not hasattr(args, attr):
            setattr(args, attr, default)
    return _cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
