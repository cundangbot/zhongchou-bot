#!/usr/bin/env python3
"""Repair duplicate/overlapping Alembic version rows for the known linear chain.

This script is intentionally conservative:
- It never changes application tables.
- It only removes lower revisions when the alembic_version table contains
  multiple rows from this exact known linear chain.
- It aborts when an unknown revision is present.

Run before ``alembic upgrade head`` when Alembic reports that one requested
revision overlaps another requested revision.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

# Allow running as ``python scripts/repair_alembic_overlap.py`` from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

KNOWN_CHAIN: tuple[str, ...] = (
    "0001_postgresql",
    "0002_support_private_bridge",
    "0003_support_admin_sessions",
    "0004_channel_discussion",
)


def _format_versions(versions: Sequence[str]) -> str:
    return ", ".join(versions) if versions else "<empty>"


async def repair(*, apply: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            table_exists = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).has_table("alembic_version")
            )
            if not table_exists:
                print("ERROR: alembic_version table does not exist; nothing was changed.", file=sys.stderr)
                return 2

            versions = list(
                (
                    await conn.execute(
                        text("SELECT version_num FROM alembic_version ORDER BY version_num")
                    )
                ).scalars()
            )
            print(f"Current alembic_version rows: {_format_versions(versions)}")

            unknown = [version for version in versions if version not in KNOWN_CHAIN]
            if unknown:
                print(
                    "ERROR: unknown Alembic revision(s) found: "
                    f"{_format_versions(unknown)}. Nothing was changed.",
                    file=sys.stderr,
                )
                return 3

            if len(versions) <= 1:
                print("No overlapping known revisions were found; nothing to repair.")
                return 0

            highest = max(versions, key=KNOWN_CHAIN.index)
            lower = [version for version in versions if version != highest]
            print(f"Highest valid revision to keep: {highest}")
            print(f"Lower duplicate revision(s) to remove: {_format_versions(lower)}")

            if not apply:
                print("Dry run only. Re-run with --apply to perform the repair.")
                return 0

            await conn.execute(
                text("DELETE FROM alembic_version WHERE version_num <> :highest"),
                {"highest": highest},
            )

            remaining = list(
                (
                    await conn.execute(
                        text("SELECT version_num FROM alembic_version ORDER BY version_num")
                    )
                ).scalars()
            )
            if remaining != [highest]:
                raise RuntimeError(
                    "Alembic version repair verification failed: "
                    f"expected [{highest}], got [{_format_versions(remaining)}]"
                )

            print(f"Repair completed. Remaining revision: {highest}")
            print("Next command: alembic upgrade head")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair duplicate rows in alembic_version for the known project migration chain."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the repair. Without this flag the script only reports the planned change.",
    )
    args = parser.parse_args()
    return asyncio.run(repair(apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
