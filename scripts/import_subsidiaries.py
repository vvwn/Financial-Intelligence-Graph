"""Import one company's subsidiaries from its annual report (CLI).

The work itself lives in `app/services/annual_report_import.py`; this file only
handles argument parsing and printing, so the batch runner and the CLI cannot
drift apart.

Usage (from repo root):
    backend/.venv/Scripts/python.exe scripts/import_subsidiaries.py --code 300308
    backend/.venv/Scripts/python.exe scripts/import_subsidiaries.py --code 300308 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.db import dispose, get_session_factory  # noqa: E402
from app.services.annual_report_import import import_for_code  # noqa: E402


async def run(code: str, apply: bool) -> int:
    factory = get_session_factory()
    async with factory() as session:
        result = await import_for_code(session, code)
        if apply and result.ok:
            await session.commit()
        else:
            await session.rollback()

    await dispose()

    if not result.ok:
        print(f"{code}: FAILED — {result.error}")
        return 2

    print(f"report: {result.report_title}")
    print(f"parsed rows: {result.parsed} (clean {result.clean})")
    if apply:
        print(f"edges created: {result.created}")
    else:
        print("dry run: nothing written (use --apply)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="stock code, e.g. 300308")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.code, args.apply)))
