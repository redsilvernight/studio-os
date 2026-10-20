from datetime import UTC, datetime
from uuid import UUID, uuid4

from studio_client.harness.credentials import pick_reusable
from studio_contracts.auth import Machine

OWNER = uuid4()
DESKTOP = uuid4()
OTHER_DESKTOP = uuid4()


def _machine(name: str, workstation_id: UUID | None, machine_id: UUID | None = None) -> Machine:
    now = datetime.now(UTC)
    return Machine(
        id=machine_id or uuid4(),
        owner_user_id=OWNER,
        display_name=name,
        workstation_id=workstation_id,
        version=1,
        created_at=now,
        updated_at=now,
    )


def test_the_ledger_machine_wins_when_still_active() -> None:
    legacy = _machine("Claude Code — PC", None)
    attached = _machine("Claude Code — PC", DESKTOP)
    picked = pick_reusable([attached, legacy], DESKTOP, DESKTOP, "Claude Code — PC", str(legacy.id))
    assert picked is legacy


def test_a_ledger_machine_of_another_workstation_is_never_taken() -> None:
    foreign = _machine("Claude Code — PC", OTHER_DESKTOP)
    assert pick_reusable([foreign], DESKTOP, DESKTOP, "Claude Code — PC", str(foreign.id)) is None


def test_reinstall_takes_the_oldest_same_name_machine_of_this_workstation() -> None:
    oldest = _machine("claude code — pc", DESKTOP)
    newer = _machine("Claude Code — PC", DESKTOP)
    other_tool = _machine("Codex — PC", DESKTOP)
    unattached = _machine("Claude Code — PC", None)
    machines = [unattached, other_tool, oldest, newer]
    assert pick_reusable(machines, DESKTOP, DESKTOP, "Claude Code — PC", None) is oldest


def test_the_desktop_machine_itself_is_never_taken() -> None:
    desktop = _machine("Claude Code — PC", DESKTOP, machine_id=DESKTOP)
    assert pick_reusable([desktop], DESKTOP, DESKTOP, "Claude Code — PC", str(DESKTOP)) is None


def test_nothing_to_take_back() -> None:
    assert pick_reusable([], DESKTOP, DESKTOP, "Claude Code — PC", None) is None
