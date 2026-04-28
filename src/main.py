from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from .config import load_settings
from .excel_io import read_retailer_names, write_results
from .pipeline import build_deps, run_pipeline


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enrich retailer data from a names-only Excel.")
    p.add_argument("--input", required=True, help="Input .xlsx with retailer names")
    p.add_argument("--output", required=True, help="Output .xlsx (two sheets written)")
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--threshold", type=float, default=None, help="Confidence cutoff (default 0.7)")
    p.add_argument("--name-column", default="name", help="Header of the column with retailer names")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    settings = load_settings()
    threshold = args.threshold if args.threshold is not None else settings.confidence_threshold

    names = read_retailer_names(args.input, args.name_column)
    if not names:
        print(f"No retailer names found in {args.input}", file=sys.stderr)
        return 1
    print(f"Processing {len(names)} retailers (concurrency={args.concurrency})...")

    Path(".cache").mkdir(exist_ok=True)

    t0 = time.monotonic()
    async with build_deps(settings) as deps:
        records = await run_pipeline(names, deps, concurrency=args.concurrency)
    elapsed = time.monotonic() - t0

    n_ok, n_review = write_results(args.output, records, threshold)
    avg_conf = sum(r.confidence for r in records) / len(records)
    print(
        f"Wrote {n_ok} enriched + {n_review} needs_review rows to {args.output} "
        f"in {elapsed:.1f}s (avg confidence {avg_conf:.2f})."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
