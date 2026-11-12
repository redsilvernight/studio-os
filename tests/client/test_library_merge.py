"""Pure three-way merge: no I/O, deterministic, structured conflicts."""

from __future__ import annotations

import pytest
from studio_client.library_merge import MergeConflict, merge_texts


@pytest.fixture(autouse=True)
def _cleanup_transfer_storage() -> None:
    """Pure merge tests need no database; keep the client suite's DB fixture out."""


def test_disjoint_edits_are_both_applied() -> None:
    result = merge_texts("one\ntwo\nthree\n", "ONE\ntwo\nthree\n", "one\ntwo\nTHREE\n")

    assert result.content == "ONE\ntwo\nTHREE\n"
    assert result.conflicts == ()
    assert not result.has_conflicts


def test_adjacent_edits_do_not_conflict() -> None:
    result = merge_texts("a\nb\nc\n", "a\nB\nc\n", "a\nb\nC\n")

    assert result.content == "a\nB\nC\n"
    assert not result.has_conflicts


def test_differing_edits_of_the_same_block_are_a_structured_conflict() -> None:
    result = merge_texts("a\nb\nc\n", "a\nours\nc\n", "a\ntheirs\nc\n")

    assert result.has_conflicts
    assert result.content == ("a\n<<<<<<< ours\nours\n=======\ntheirs\n>>>>>>> theirs\nc\n")
    assert result.conflicts == (
        MergeConflict(
            start_line=2,
            base_start=1,
            base_end=2,
            base="b\n",
            ours="ours\n",
            theirs="theirs\n",
        ),
    )


def test_identical_additions_are_applied_once() -> None:
    result = merge_texts("a\nb\n", "a\nx\nb\n", "a\nx\nb\n")

    assert result.content == "a\nx\nb\n"
    assert not result.has_conflicts


def test_identical_deletions_are_applied_once() -> None:
    result = merge_texts("a\nb\nc\n", "a\nc\n", "a\nc\n")

    assert result.content == "a\nc\n"
    assert not result.has_conflicts


def test_different_insertions_at_the_same_point_conflict() -> None:
    result = merge_texts("a\nb\n", "a\nx\nb\n", "a\ny\nb\n")

    assert result.has_conflicts
    conflict = result.conflicts[0]
    assert (conflict.base_start, conflict.base_end) == (1, 1)
    assert conflict.base == ""
    assert conflict.ours == "x\n"
    assert conflict.theirs == "y\n"
    assert result.content == "a\n<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\nb\n"


def test_insertion_at_the_end_of_a_deletion_stays_clean() -> None:
    result = merge_texts("a\nb\nc\n", "a\nc\n", "a\nb\nx\nc\n")

    assert result.content == "a\nx\nc\n"
    assert not result.has_conflicts


def test_empty_inputs() -> None:
    empty = merge_texts("", "", "")
    assert empty.content == ""
    assert empty.conflicts == ()

    added = merge_texts("", "x\n", "x\n")
    assert added.content == "x\n"
    assert not added.has_conflicts

    conflict = merge_texts("", "x\n", "y\n")
    assert conflict.content == "<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n"
    assert conflict.conflicts[0].base == ""


def test_empty_side_deletes_the_base_cleanly() -> None:
    both = merge_texts("a\n", "", "")
    assert both.content == ""
    assert not both.has_conflicts

    one = merge_texts("a\n", "", "a\n")
    assert one.content == ""
    assert not one.has_conflicts


def test_one_side_adds_to_an_empty_base() -> None:
    result = merge_texts("", "x\n", "")

    assert result.content == "x\n"
    assert not result.has_conflicts


def test_mixed_crlf_and_lf_are_normalised_without_spurious_conflicts() -> None:
    result = merge_texts(
        "a\r\nb\r\nc\r\n",
        "A\nb\r\nc\n",
        "a\r\nb\r\nC\r\n",
    )

    assert result.content == "A\nb\nC\n"
    assert not result.has_conflicts


def test_conflicted_crlf_input_renders_lf_markers() -> None:
    result = merge_texts("a\r\nb", "a\r\nO", "a\r\nT")

    assert result.content == ("a\n<<<<<<< ours\nO\n=======\nT\n>>>>>>> theirs\n")
    assert result.conflicts[0].ours == "O"
    assert result.conflicts[0].theirs == "T"


def test_missing_final_newline_is_preserved_on_clean_merge() -> None:
    result = merge_texts("a\nb", "A\nb", "a\nB")

    assert result.content == "A\nB"
    assert not result.content.endswith("\n")
    assert not result.has_conflicts


@pytest.mark.parametrize(
    ("base", "ours", "theirs"),
    [
        ("a", "a", "a"),
        ("a\nb", "a\nb", "a\nb"),
        ("a\nb", "a\nx\nb", "a\nx\nb"),
    ],
)
def test_unterminated_last_line_stays_unterminated(base: str, ours: str, theirs: str) -> None:
    result = merge_texts(base, ours, theirs)

    assert result.content == ours
    assert not result.content.endswith("\n")
    assert not result.has_conflicts


def test_result_is_independent_of_call_order() -> None:
    first = merge_texts("a\nb\nc\n", "A\nb\nc\n", "a\nb\nC\n")
    merge_texts("x\ny\n", "X\ny\n", "x\nY\n")
    second = merge_texts("a\nb\nc\n", "A\nb\nc\n", "a\nb\nC\n")

    assert first == second


def test_clean_result_does_not_depend_on_side_order() -> None:
    base = "a\nb\nc\nd\n"
    ours = "A\nb\nc\nd\n"
    theirs = "a\nb\nC\nd\n"

    forward = merge_texts(base, ours, theirs)
    reverse = merge_texts(base, theirs, ours)

    assert forward.content == reverse.content == "A\nb\nC\nd\n"
    assert not forward.has_conflicts
    assert not reverse.has_conflicts


def test_conflict_line_numbers_follow_output_order() -> None:
    result = merge_texts(
        "a\nb\nc\nd\ne\n",
        "a\nB1\nc\nD1\ne\n",
        "a\nB2\nc\nD2\ne\n",
    )

    assert [conflict.start_line for conflict in result.conflicts] == [2, 8]
    assert [conflict.base for conflict in result.conflicts] == ["b\n", "d\n"]


def test_custom_labels_and_invalid_labels() -> None:
    result = merge_texts("a\n", "x\n", "y\n", ours_label="override", theirs_label="upstream")
    assert result.content == "<<<<<<< override\nx\n=======\ny\n>>>>>>> upstream\n"

    with pytest.raises(ValueError, match="single-line"):
        merge_texts("a\n", "x\n", "y\n", ours_label="two\nlines")
    with pytest.raises(ValueError, match="non-empty"):
        merge_texts("a\n", "x\n", "y\n", theirs_label="")


def test_swapping_sides_swaps_conflict_content() -> None:
    forward = merge_texts("a\n", "x\n", "y\n")
    reverse = merge_texts("a\n", "y\n", "x\n")

    assert forward.conflicts[0].ours == reverse.conflicts[0].theirs
    assert forward.conflicts[0].theirs == reverse.conflicts[0].ours
