"""One-shot, idempotent migration of `docs/DECISIONS.md` into unit ADRs
under `docs/decisions/` (Phase 4 of the Studio OS Graphify overhaul).

This is a *bootstrap*: once a `DEC-XXXX` has a corresponding ADR file, this
tool never touches its content again, even if the source log or the vault
note changes afterwards -- the ADR is the new canonical source, so nothing
should silently overwrite a hand-edited ADR (that is what made
`docs/DECISIONS.md` unworkable in the first place: 2000+ lines everyone kept
hand-editing). Adding decision number 33 after migration means adding a new
`docs/decisions/DEC-0033-*.md` file directly, not editing DECISIONS.md.

Only fields that are actually known (from the source log, or from an
existing vault note matched by its `DEC-XXXX` alias) are ever written --
never fabricated. See `adr_common.build_adr_frontmatter` for exactly which
fields come from where.

Usage (run as a module so the package-relative import resolves):
    uv run python -m scripts.adr_migrate --root . --check   # report only
    uv run python -m scripts.adr_migrate --root . --apply   # write ADR files
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .adr_common import (
    adr_filename,
    build_adr_frontmatter,
    content_hash,
    index_vault_notes_by_dec_id,
    parse_decisions_log,
    render_adr_markdown,
)

SOURCE_RELPATH = "docs/DECISIONS.md"
DECISIONS_DIR_RELPATH = "docs/decisions"
PREAMBLE_FILENAME = "_preamble.md"
DEFAULT_VAULT_DIR = Path(r"E:\LocalAI\AI-Memory\projects\studio-os\decisions")


@dataclass
class MigrationPlan:
    to_create: list[tuple[str, Path, str]]  # (dec_id, target_path, content)
    already_migrated: list[str]  # dec_ids that already have an ADR file
    preamble_to_write: str | None  # None if _preamble.md already exists or there's nothing to write


def find_existing_adr(decisions_dir: Path, dec_id: str) -> Path | None:
    matches = sorted(decisions_dir.glob(f"{dec_id}-*.md"))
    return matches[0] if matches else None


def plan_migration(root: Path, vault_dir: Path = DEFAULT_VAULT_DIR) -> MigrationPlan:
    source_path = root / SOURCE_RELPATH
    decisions_dir = root / DECISIONS_DIR_RELPATH

    log = parse_decisions_log(source_path.read_text(encoding="utf-8"))
    vault_index = index_vault_notes_by_dec_id(vault_dir)

    to_create: list[tuple[str, Path, str]] = []
    already_migrated: list[str] = []
    for decision in log.decisions:
        existing = find_existing_adr(decisions_dir, decision.id)
        if existing is not None:
            already_migrated.append(decision.id)
            continue
        vault_note = vault_index.get(decision.id)
        fields = build_adr_frontmatter(
            dec_id=decision.id,
            title=decision.title,
            source=SOURCE_RELPATH,
            sync_hash=content_hash(decision.body),
            vault_note=vault_note,
        )
        content = render_adr_markdown(fields, decision.body)
        target = decisions_dir / adr_filename(decision.id, decision.title)
        to_create.append((decision.id, target, content))

    preamble_path = decisions_dir / PREAMBLE_FILENAME
    preamble_to_write = log.preamble if log.preamble and not preamble_path.exists() else None

    return MigrationPlan(
        to_create=to_create, already_migrated=already_migrated, preamble_to_write=preamble_to_write
    )


def apply_migration(root: Path, plan: MigrationPlan) -> None:
    decisions_dir = root / DECISIONS_DIR_RELPATH
    decisions_dir.mkdir(parents=True, exist_ok=True)
    for _dec_id, target, content in plan.to_create:
        target.write_text(content, encoding="utf-8", newline="\n")
    if plan.preamble_to_write is not None:
        (decisions_dir / PREAMBLE_FILENAME).write_text(
            plan.preamble_to_write + "\n", encoding="utf-8", newline="\n"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--vault-dir", type=Path, default=DEFAULT_VAULT_DIR)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plan = plan_migration(args.root, args.vault_dir)
    print(
        f"a migrer: {len(plan.to_create)}, deja migres: {len(plan.already_migrated)}, "
        f"preambule a ecrire: {plan.preamble_to_write is not None}"
    )
    for dec_id, target, _content in plan.to_create:
        print(f"  {dec_id} -> {target.relative_to(args.root)}")

    if args.apply:
        apply_migration(args.root, plan)
        print("migration appliquee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
