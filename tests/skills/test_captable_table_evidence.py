"""Source provenance regressions: realistic certificates, columns and holders."""
import pytest

from lib.captable.table_extraction import _review_table_evidence


REGISTER = """| Holder | Certificate | Common shares | Preferred shares |
| --- | --- | --- | --- |
| Alice | 12 | 100 | 50 |
| | 13 | 100 | 50 |
| Bob | 14 | 300 | - |"""
ALICE = "| Alice | 12 | 100 | 50 |\n| | 13 | 100 | 50 |"


def review(document, quote, value, *, name="Alice", field="current_common"):
    return _review_table_evidence(document)({"entries": [{"name": name, field: value, "quote": quote}]}).problems


def test_duplicate_amounts_are_preserved_when_summing_certificates():
    assert not review(REGISTER, ALICE, 200)
    assert review(REGISTER, ALICE, 100)  # not an arbitrary subset


@pytest.mark.parametrize("value", [12, 25, 112, 125, 225, 300, 12100, 1250100])
def test_certificate_ids_other_columns_and_joined_digits_are_not_shares(value):
    assert review(REGISTER, ALICE, value)


def test_unrelated_holder_cannot_supply_evidence_even_when_name_exists():
    assert review(REGISTER, "| Bob | 14 | 300 | - |", 300)
    assert review(REGISTER, ALICE + "\n| Bob | 14 | 300 | - |", 500)


def test_merged_owner_does_not_cross_next_named_holder():
    document = REGISTER + "\n| | 15 | 500 | - |"
    assert review(document, "| | 15 | 500 | - |", 500)
    assert not review(document, "| | 15 | 500 | - |", 500, name="Bob")


def test_empty_cell_and_other_columns_dash_do_not_prove_zero():
    assert review(REGISTER, "| | 13 | 100 | 50 |", 0)
    assert review(REGISTER, "| Bob | 14 | 300 | - |", 0, name="Bob")
    assert not review(REGISTER, "| Bob | 14 | 300 | - |", 0, name="Bob", field="current_preferred")


@pytest.mark.parametrize("marker", ["", "n/a", "NA"])
def test_unknown_cell_is_not_automatically_zero(marker):
    document = f"| Holder | Shares |\n| --- | --- |\n| Alice | {marker} |"
    assert review(document, f"| Alice | {marker} |", 0)


def test_quoted_certificate_cannot_be_repeated_to_inflate_a_total():
    line = "| Alice | 12 | 100 | 50 |"
    assert review(REGISTER, line + "\n" + line, 200)


def test_same_amount_in_distinct_identical_source_rows_counts_twice():
    line = "| Alice | 100 |"
    document = "| Holder | Shares |\n| --- | --- |\n" + line + "\n" + line
    assert not review(document, line + "\n" + line, 200)


def test_zero_marker_must_be_quoted_in_its_source_cell():
    document = "| Holder | Common shares | Preferred shares |\n| --- | --- | --- |\n| Alice | 100 | - |"
    # A fabricated column shift cannot pass normalized substring matching.
    assert review(document, "| Alice | - | 100 |", 0)


def test_digits_are_not_joined_across_cells_even_without_headers():
    assert review("| Alice | 12 | 345 |", "| Alice | 12 | 345 |", 12345)
    assert review("| Alice | 12 | 345 |", "| Alice | 12345 |", 12345)


def test_repaired_numeral_is_not_a_substring_of_another_amount():
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 21'66 6 |"
    assert not review(document, "| Alice | 21'66 6 |", 21666)
    assert review(document, "| Alice | 21'66 6 |", 1666)


def test_two_numerals_in_a_collapsed_cell_remain_ambiguous():
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 12'036 21'66 6 |"
    assert review(document, "| Alice | 12'036 21'66 6 |", 21666)


def test_name_tokens_from_different_people_do_not_create_a_holder():
    document = "| Alice Jones | 100 |\n| Bob Smith | 200 |"
    assert review(document, "| Bob Smith | 200 |", 200, name="Alice Smith")


def test_class_nominal_is_evidenced_on_a_holder_row_with_that_class():
    from lib.captable.table_extraction import _review_captable
    document = "| Holder | Common issued | Preferred issued | Nominal (CHF) |\n| --- | --- | --- | --- |\n| Alice | 100 | | 0.10 |"
    row = {"id": "common", "name": "Common", "nominal_value": 0.1, "quote": "| Alice | 100 | | 0.10 |"}
    assert not _review_captable(document)({"share_classes": [row]}).problems
    row["id"] = "preferred"
    row["name"] = "Preferred"
    assert _review_captable(document)({"share_classes": [row]}).problems


def test_nominal_in_class_definition_prose_does_not_use_share_count():
    from lib.captable.table_extraction import _review_captable
    document = "800,000 registered common shares with a nominal value of CHF 0.10 each."
    row = {"id": "common", "name": "common", "nominal_value": 0.1, "quote": document}
    assert not _review_captable(document)({"share_classes": [row]}).problems
    row["nominal_value"] = 800000
    assert _review_captable(document)({"share_classes": [row]}).problems


def test_unknown_operand_cannot_be_dropped_from_a_total():
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 100 |\n| Alice | |"
    assert review(document, "| Alice | 100 |\n| Alice | |", 100)


def test_markdown_separator_is_allowed_as_quoted_context():
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 100 |"
    assert not review(document, document, 100)


def test_group_context_never_becomes_a_numeric_operand():
    from lib.captable.table_extraction import _review_captable
    document = "| Group | Common issued |\n| --- | --- |\n| Founders | 1000 |\n| Alice | 100 |"
    row = {"name": "Alice", "group": "Founders", "holdings": [{"class_id": "common", "count": 100}], "quote": document}
    assert not _review_captable(document)({"stakeholders": [row]}).problems
    row["holdings"][0]["count"] = 1100
    assert _review_captable(document)({"stakeholders": [row]}).problems


def test_non_numeric_context_does_not_crash_number_parser():
    from lib.captable.table_evidence import numbers
    assert numbers('references 1,2,3') == []


def test_other_holder_context_cannot_change_selected_holding():
    assert not review(REGISTER, ALICE + "\n| Bob | 14 | 300 | - |", 200)
    assert review(REGISTER, ALICE + "\n| Bob | 14 | 300 | - |", 300)


def test_grantable_pool_uses_its_own_diluted_column_not_investment():
    document = "| Group | Diluted shares | Investment |\n| --- | --- | --- |\n| Equity plans grantable | 25000 | 90000 |"
    row = {"kind": "grantable", "label": "Equity plans grantable", "total": 25000, "unallocated": 25000, "quote": document}
    assert not _review_table_evidence(document)({"pools": [row]}).problems
    row["total"] = 90000
    assert _review_table_evidence(document)({"pools": [row]}).problems
