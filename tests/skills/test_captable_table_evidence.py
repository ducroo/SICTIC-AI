"""Evidence rules for extracted table rows (lib/captable/table_evidence.py).

Fixtures use invented identities. The adversarial cases in the first part
were contributed on the review of PR #71 and are kept verbatim except where
a comment states a deliberate difference.
"""
import pytest

from lib.captable.table_evidence import Source, numbers, resolve_quote, QuoteError
from lib.captable.table_extraction import _review_captable, _review_table_evidence


REGISTER = """| Holder | Certificate | Common shares | Preferred shares |
| --- | --- | --- | --- |
| Alice | 12 | 100 | 50 |
| | 13 | 100 | 50 |
| Bob | 14 | 300 | - |"""
ALICE = "| Alice | 12 | 100 | 50 |\n| | 13 | 100 | 50 |"


def review(document, quote, value, *, name="Alice", field="current_common"):
    return _review_table_evidence(document)({"entries": [{"name": name, field: value, "quote": quote}]}).problems


# --- source-row guarantees ------------------------------------------------

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
    problems = review(document, f"| Alice | {marker} |", 0)
    assert problems and "null, never 0" in problems[0]


def test_absent_column_is_not_zero():
    document = "| Holder | Common shares |\n| --- | --- |\n| Alice | 100 |"
    assert review(document, "| Alice | 100 |", 0, field="current_preferred")
    assert not review(document, "| Alice | 100 |", None, field="current_preferred")


def test_quoted_certificate_cannot_be_repeated_to_inflate_a_total():
    line = "| Alice | 12 | 100 | 50 |"
    assert review(REGISTER, line + "\n" + line, 200)


def test_same_amount_in_distinct_identical_source_rows_counts_twice():
    line = "| Alice | 100 |"
    document = "| Holder | Shares |\n| --- | --- |\n" + line + "\n" + line
    assert not review(document, line + "\n" + line, 200)


def test_zero_marker_must_be_quoted_in_its_source_cell():
    document = "| Holder | Common shares | Preferred shares |\n| --- | --- | --- |\n| Alice | 100 | - |"
    assert review(document, "| Alice | - | 100 |", 0)


def test_digits_are_not_joined_across_cells_even_without_headers():
    assert review("| Alice | 12 | 345 |", "| Alice | 12 | 345 |", 12345)
    assert review("| Alice | 12 | 345 |", "| Alice | 12345 |", 12345)


def test_repaired_numeral_is_not_a_substring_of_another_amount():
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 21'66 6 |"
    assert not review(document, "| Alice | 21'66 6 |", 21666)
    assert review(document, "| Alice | 21'66 6 |", 1666)


def test_stacked_history_cell_states_each_of_its_figures():
    # Deliberate difference from the review suite: a register cell stacks a
    # holder's historical counts (see register_extraction_prompt.md), so
    # either figure is stated by the source; which one is current is the
    # model's call, recorded in assumptions.
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 12'036 21'66 6 |"
    assert not review(document, "| Alice | 12'036 21'66 6 |", 21666)
    assert not review(document, "| Alice | 12'036 21'66 6 |", 12036)
    assert review(document, "| Alice | 12'036 21'66 6 |", 33702)  # never their sum


def test_name_tokens_from_different_people_do_not_create_a_holder():
    document = "| Alice Jones | 100 |\n| Bob Smith | 200 |"
    assert review(document, "| Bob Smith | 200 |", 200, name="Alice Smith")


def test_class_nominal_is_evidenced_on_a_holder_row_with_that_class():
    document = "| Holder | Common issued | Preferred issued | Nominal (CHF) |\n| --- | --- | --- | --- |\n| Alice | 100 | | 0.10 |"
    row = {"id": "common", "name": "Common", "nominal_value": 0.1, "quote": "| Alice | 100 | | 0.10 |"}
    assert not _review_captable(document)({"share_classes": [row]}).problems
    row["id"] = "preferred"
    row["name"] = "Preferred"
    assert _review_captable(document)({"share_classes": [row]}).problems


def test_nominal_in_class_definition_prose_does_not_use_share_count():
    document = "800,000 registered common shares with a nominal value of CHF 0.10 each."
    row = {"id": "common", "name": "common", "nominal_value": 0.1, "quote": document}
    assert not _review_captable(document)({"share_classes": [row]}).problems
    row["nominal_value"] = 800000
    assert _review_captable(document)({"share_classes": [row]}).problems


def test_blank_operand_states_nothing_for_a_total():
    # Deliberate difference from the review suite: a blank cell evidences
    # nothing, so the only stated figure is what the holder's rows report.
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 100 |\n| Alice | |"
    assert not review(document, "| Alice | 100 |\n| Alice | |", 100)
    assert review(document, "| Alice | 100 |\n| Alice | |", 0)


def test_markdown_separator_is_allowed_as_quoted_context():
    document = "| Holder | Shares |\n| --- | --- |\n| Alice | 100 |"
    assert not review(document, document, 100)


def test_group_context_never_becomes_a_numeric_operand():
    document = "| Group | Common issued |\n| --- | --- |\n| Founders | 1000 |\n| Alice | 100 |"
    row = {"name": "Alice", "group": "Founders", "holdings": [{"class_id": "common", "count": 100}], "quote": document}
    assert not _review_captable(document)({"stakeholders": [row]}).problems
    row["holdings"][0]["count"] = 1100
    assert _review_captable(document)({"stakeholders": [row]}).problems


def test_non_numeric_context_does_not_crash_number_parser():
    assert numbers("references 1,2,3") == []


def test_other_holder_context_cannot_change_selected_holding():
    assert not review(REGISTER, ALICE + "\n| Bob | 14 | 300 | - |", 200)
    assert review(REGISTER, ALICE + "\n| Bob | 14 | 300 | - |", 300)


def test_grantable_pool_uses_its_own_diluted_column_not_investment():
    document = "| Group | Diluted shares | Investment |\n| --- | --- | --- |\n| Equity plans grantable | 25000 | 90000 |"
    row = {"kind": "grantable", "label": "Equity plans grantable", "total": 25000, "unallocated": 25000, "quote": document}
    assert not _review_table_evidence(document)({"pools": [row]}).problems
    row["total"] = 90000
    assert _review_table_evidence(document)({"pools": [row]}).problems


# --- real-world layouts ---------------------------------------------------

YEAR_SHEET = """| Shareholder | 2024 (shares) | 2025 (shares) | 2026 (plan) | % |
| --- | --- | --- | --- | --- |
| Alice Example | 8'000 | 8'000 | 12'000 | 40.0% |
| Bob Example | 12'000 | 12'000 | 18'000 | 60.0% |
| Total | 20'000 | 20'000 | 30'000 | 100% |"""


def test_year_columns_with_abbreviated_quote_are_matched_cell_by_cell():
    row = {"name": "Alice Example", "kind": "founder", "role": "founder",
           "holdings": [{"class_id": "common", "count": 8000}], "quote": "| Alice Example | 8'000 |"}
    assert not _review_captable(YEAR_SHEET)({"stakeholders": [row]}).problems
    row["holdings"][0]["count"] = 80008000  # digits of two cells
    assert _review_captable(YEAR_SHEET)({"stakeholders": [row]}).problems


def test_punctuation_only_cells_and_trailing_empties_do_not_block_a_match():
    document = ("| | Group | # | Common | | | Note | | Preferred | | | | | |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| | Total Series A pool, unallocated | # | 478933 | | | internal | | 187327 | | | | | |")
    row = {"kind": "grantable", "label": "Total Series A pool, unallocated", "total": 478933, "granted": None,
           "unallocated": None, "quote": "|  | Total Series A pool, unallocated | # | 478933 |  |  | internal |  | 187327 |"}
    assert not _review_table_evidence(document)({"pools": [row]}).problems


def test_single_class_sheet_names_its_class_in_year_headers():
    row = {"id": "shares", "name": "Shares", "nominal_value": None, "votes_per_share": None,
           "quote": "| Total | 20'000 | 20'000 | 30'000 | 100% |"}
    assert not _review_captable(YEAR_SHEET)({"share_classes": [row]}).problems
    row["quote"] = "| Bob Example | 12'000 |"
    assert not _review_captable(YEAR_SHEET)({"share_classes": [row]}).problems


def test_quoted_bullet_list_spans_adjacent_source_lines():
    document = "Grants under the Plan:\n\n- Managing Director: 500 options\n\n- Head of Sales: 200 options\n\n- Advisor: 50 options\n\nVesting over four years."
    row = {"kind": "esop", "label": "Plan", "total": None, "granted": None, "unallocated": None,
           "quote": "Grants under the Plan: - Managing Director: 500 options - Head of Sales: 200 options - Advisor: 50 options"}
    assert not _review_table_evidence(document)({"pools": [row]}).problems
    row["quote"] = "Grants under the Plan: - Managing Director: 600 options"
    assert _review_table_evidence(document)({"pools": [row]}).problems


def test_escaped_pipe_inside_a_cell_may_be_quoted_as_a_cell_boundary():
    document = ("| No | Holder | Note | Shares |\n| --- | --- | --- | --- |\n"
                "| 3 | Alice Example | 757 15. &#124;I transfer of 85 shares | 85 |")
    assert not review(document, "| 3 | Alice Example | 757 15. |I transfer of 85 shares | 85 |", 85, name="Alice Example")
    assert review(document, "| 3 | Alice Example | 757 15. |I transfer of 85 shares | 85 |", 124, name="Alice Example")


def test_share_class_named_only_by_year_headers_may_quote_the_header():
    row = {"id": "shares", "name": "Shares", "nominal_value": None, "votes_per_share": None,
           "quote": "| Shareholder | 2024 (shares) | 2025 (shares) | 2026 (plan) | % |"}
    assert not _review_captable(YEAR_SHEET)({"share_classes": [row]}).problems
    row["name"] = "Preferred"
    assert _review_captable(YEAR_SHEET)({"share_classes": [row]}).problems


def test_third_pool_figure_may_be_derived_from_two_stated_ones():
    document = "| Pool | Size | Granted |\n| --- | --- | --- |\n| ESOP 2024 | 10000000 | 1000000 |"
    row = {"kind": "esop", "label": "ESOP 2024", "total": 10000000, "granted": 1000000, "unallocated": 9000000,
           "quote": "| ESOP 2024 | 10000000 | 1000000 |"}
    assert not _review_table_evidence(document)({"pools": [row]}).problems
    row["unallocated"] = 8000000
    assert _review_table_evidence(document)({"pools": [row]}).problems
    row["unallocated"] = None
    assert not _review_table_evidence(document)({"pools": [row]}).problems


def test_dropped_middle_cell_in_a_quoted_row_is_tolerated():
    document = "| No | Holder | Certificate | Shares |\n| --- | --- | --- | --- |\n| 1 | Alice Example | 12 | 100 |"
    assert not review(document, "| 1 | Alice Example | 100 |", 100, name="Alice Example")
    assert review(document, "| 1 | Alice Example | 12100 |", 12100, name="Alice Example")


OCR_REGISTER = """<!-- source-page:3 -->

| Example Holdings AG Bahnhofstrasse 1 8001 Zurich 1'388'001 | 13'880.01 | 50% | 13.88% 6.75% | Capital increase, 27.04.2022 | | | 5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | 256.31 | 100% | 0.12% | Capital increase, 13.01.2023 | Allocation 21 | | Zurich |
| 1 ' 351 ' 622 | 13 ' 516.22 | 50% | | | Allocation 23 | 20.06.2024 | |
| 825'472 1'348'098 | 8 ' 254.72 | 50% 100% | 4.01% | | Allocation 23 paid-up | 19.06.2025 | |
| | 13'480.98 | 100% | 6.55% | Allocation 2, 16.12.2025 | Shares | 01.09.2025 | |
| Carol Example Seestrasse 5 8002 Zurich | 25'631 | 100% | | | | | 6 |

<!-- source-page:4 -->

| 30 | 28 5 ' | 135 | 51.35 | 50% 100% | 0.02% | Allocation 5, 19.06.2025 | Shares paid-up | 01.09.2025 | Dan Example Hauptstrasse 9 8003 Zurich |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 31 | 48 9 ' | 629 | 96.29 | 50% 100% | 0.05% | Allocation 5, 19.06.2025 | Shares paid-up | 01.09.2025 | Erin Example Dorfstrasse 2 8004 Zurich |"""


def test_ocr_register_first_row_is_a_holder_not_a_header():
    quote = "| Example Holdings AG Bahnhofstrasse 1 8001 Zurich 1'388'001 | 13'880.01 | 50% |"
    assert not review(OCR_REGISTER, quote, 1388001, name="Example Holdings AG")


def test_nameless_history_rows_belong_to_the_named_row_above():
    quote = ("| Example Holdings AG Bahnhofstrasse 1 8001 Zurich 1'388'001 | 13'880.01 |\n"
             "| 825'472 1'348'098 | 8 ' 254.72 | 50% 100% | 4.01% |\n"
             "| | 13'480.98 | 100% | 6.55% |")
    assert not review(OCR_REGISTER, quote, 1348098, name="Example Holdings AG")
    assert not review(OCR_REGISTER, quote, 6.55, name="Example Holdings AG", field="current_participation_pct")
    assert review(OCR_REGISTER, quote, 1348098, name="Carol Example")


def test_orphan_row_at_page_top_does_not_belong_to_a_later_holder():
    quote = "| | 256.31 | 100% | 0.12% |\n| Carol Example Seestrasse 5 8002 Zurich | 25'631 | 100% |"
    assert not review(OCR_REGISTER, quote, 25631, name="Carol Example")
    assert review(OCR_REGISTER, quote, 0.12, name="Carol Example", field="current_participation_pct")


def test_numeral_split_at_a_dangling_apostrophe_is_joined_across_the_cell_boundary():
    quote = "| 30 | 28 5 ' | 135 | 51.35 | 50% 100% | 0.02% | Allocation 5, 19.06.2025 | Shares paid-up | 01.09.2025 | Dan Example Hauptstrasse 9 8003 Zurich |"
    assert not review(OCR_REGISTER, quote, 5135, name="Dan Example")
    assert review(OCR_REGISTER, quote, 28135, name="Dan Example")


def test_page_markers_do_not_split_a_continued_table():
    document = ("| No | Holder | Certificate | Shares |\n| --- | --- | --- | --- |\n"
                "| 1 | Alice Example | 12 | 100 |\n| | | 13 | 250 |\n"
                "<!-- page:2 -->\n\n| | | 14 | 400 |\n| 2 | Bob Example | 15 | - |")
    assert not review(document, "| | | 14 | 400 |", 400, name="Alice Example")
    assert not review(document, "| 1 | Alice Example | 12 | 100 |\n| | | 13 | 250 |\n| | | 14 | 400 |", 750, name="Alice Example")
    assert review(document, "| | | 14 | 400 |", 400, name="Bob Example")


def test_a_table_declaring_its_own_text_header_after_a_page_break_is_a_new_table():
    document = ("| Holder | Certificate | Shares |\n| --- | --- | --- |\n| Alice Example | 12 | 100 |\n| | 13 | 250 |\n"
                "<!-- page:2 -->\n\n| Pool | Granted | Unallocated |\n| --- | --- | --- |\n| ESOP | 10 | 90 |")
    rows = [line for line in Source(document).lines if line.kind == "row"]
    assert len({line.table for line in rows}) == 2
    assert rows[-1].headers == ("Pool", "Granted", "Unallocated")
    assert not review(document, "| Alice Example | 12 | 100 |\n| | 13 | 250 |", 350, name="Alice Example")
    assert review(document, "| ESOP | 10 | 90 |", 90, name="Alice Example")   # the new table's row is not hers


def test_nameless_rows_below_a_running_page_header_belong_to_the_holder_before_the_break():
    document = ("| No | Holder | Certificate | Shares |\n| --- | --- | --- | --- |\n| 1 | Alice Example | 12 | 100 |\n\n"
                "<!-- page:2 -->\n\nShare register, page 2\n\n"
                "| | | 13 | 250 |\n| --- | --- | --- | --- |\n| | | 14 | 400 |\n| 2 | Bob Example | 15 | - |")
    quote = "| 1 | Alice Example | 12 | 100 |\n| | | 13 | 250 |\n| | | 14 | 400 |"
    assert not review(document, quote, 750, name="Alice Example")
    assert review(document, "| | | 13 | 250 |\n| 2 | Bob Example | 15 | - |", 250, name="Bob Example")
    assert review(document, "| | | 13 | 250 |", 13, name="Alice Example")   # inherited header excludes the certificate column


SHEET_WITH_SECTIONS = """## Loan pool (phantom)

| | | |
| --- | --- | --- |
| Loan Pool - Phantom Stock Option Plan (v3, 27.05.2026) | | |
| Description: cash-settled, no shares issued | | |
| Key figures | | |
| Number shares granted | 1000000 | |
| Number of grantees | 17 | |
| Pool base (nominal shares) | 10000000 | |"""


def test_pool_named_by_a_section_row_of_the_same_sheet():
    row = {"kind": "psop", "label": "Loan Pool - Phantom Stock Option Plan", "total": 10000000,
           "granted": 1000000, "unallocated": None,
           "quote": "| Number shares granted | 1000000 |\n| Pool base (nominal shares) | 10000000 |"}
    assert not _review_table_evidence(SHEET_WITH_SECTIONS)({"pools": [row]}).problems
    row["label"] = "Employee Stock Option Plan"
    assert _review_table_evidence(SHEET_WITH_SECTIONS)({"pools": [row]}).problems


POOL_SHEET = """| Row Label | Sum of Pool: Total | Sum of Pool: Total | | Pool | Pool |
| --- | --- | --- | --- | --- | --- |
| | | | | | |
| | Conditional capital pool (art. 3a) | | 259059 | | 32547 |
| | Total Series pool, unallocated | # | 478933 | | 14982 |"""


def test_pool_named_on_one_row_and_stated_on_another_row_of_the_same_sheet():
    row = {"kind": "grantable", "label": "Conditional capital pool", "total": 259059, "granted": 32547,
           "unallocated": 14982,
           "quote": "| | Conditional capital pool (art. 3a) | | 259059 | | 32547 |\n| | Total Series pool, unallocated | # | 478933 | | 14982 |"}
    assert not _review_table_evidence(POOL_SHEET)({"pools": [row]}).problems
    row["quote"] = "| | Total Series pool, unallocated | # | 478933 | | 14982 |"
    assert _review_table_evidence(POOL_SHEET)({"pools": [row]}).problems   # nothing quoted names the pool


def test_holder_rows_never_borrow_from_another_quoted_holder_row():
    problems = review(REGISTER, "| Alice | 12 | 100 | 50 |\n| Bob | 14 | 300 | - |", 300)
    assert problems and "was ignored" in problems[0] and "| Bob | 14 | 300 | - |" in problems[0]
    assert "report null" in problems[0]


PLAN_LETTER = """## Written resolutions of the board

Issue Date:

January 1 st , 2024

## 1. Regulations of the Phantom Stock Option Plan (the 'Plan')

The maximum number of shares of Phantom Stock allotted under the Plan shall not exceed 10% of the Share Capital. Grants vest over four years."""


def test_pool_named_by_a_document_heading_and_date_across_blank_lines():
    row = {"kind": "psop", "label": "Phantom Stock Option Plan", "total": None, "granted": None,
           "unallocated": None, "quote": "The maximum number of shares of Phantom Stock allotted under the Plan shall not exceed 10% of the Share Capital."}
    output = {"pools": [row], "as_of_date": {"value": "2024-01-01", "quote": "Issue Date: January 1 st , 2024"}}
    assert not _review_table_evidence(PLAN_LETTER)({**output}).problems
    output["as_of_date"]["quote"] = "Issue Date: February 1 st , 2024"
    assert _review_table_evidence(PLAN_LETTER)(output).problems


PARAMETER_SHEET = """| | | | |
| --- | --- | --- | --- |
| | Nominal value per share | CHF | 1 |
| | | | |
| Holder | Status | Pool: Common Shares | Pool: Preferred Shares |
| Alice Example | active | 8'000 | 2'000 |"""


def test_share_class_named_by_a_label_row_of_the_same_sheet():
    row = {"id": "common", "name": "Common Shares", "nominal_value": 1, "votes_per_share": None,
           "quote": "| | Nominal value per share | CHF | 1 |"}
    assert not _review_captable(PARAMETER_SHEET)({"share_classes": [row]}).problems
    row["name"] = "Series B Shares"
    assert _review_captable(PARAMETER_SHEET)({"share_classes": [row]}).problems


@pytest.mark.parametrize("document, preferred_header", [
    ("| Aktionär | Stammaktien | Vorzugsaktien Serie A | Anteil |\n| --- | --- | --- | --- |\n| Alice Example | 8'000 | 2'000 | 40.0% |", "Vorzugsaktien"),
    ("| Actionnaire | Actions ordinaires | Actions privilégiées | Part |\n| --- | --- | --- | --- |\n| Alice Example | 8'000 | 2'000 | 40.0% |", "privilégiées"),
])
def test_german_and_french_headers_bind_classes_and_exclude_percentages(document, preferred_header):
    quote = document.splitlines()[-1]
    holdings = [{"class_id": "common", "count": 8000}, {"class_id": "preferred_a", "count": 2000}]
    row = {"name": "Alice Example", "kind": "founder", "role": "founder", "holdings": holdings, "quote": quote}
    assert not _review_captable(document)({"stakeholders": [row]}).problems
    holdings[0]["count"] = 2000  # the preferred column cannot evidence common
    assert _review_captable(document)({"stakeholders": [row]}).problems
    holdings[0]["count"] = 40  # nor can the percentage column
    assert _review_captable(document)({"stakeholders": [row]}).problems


def test_holder_named_in_prose_directly_above_its_table():
    document = "Shareholder: Alice Example\n\n| Certificate | Shares |\n| --- | --- |\n| 12 | 100 |\n| 13 | 250 |"
    assert not review(document, "| 12 | 100 |\n| 13 | 250 |", 350, name="Alice Example")
    assert review(document, "| 12 | 100 |\n| 13 | 250 |", 350, name="Bob Example")


# --- feedback -------------------------------------------------------------

def test_rejection_names_the_closest_source_line_and_the_stated_numbers():
    problems = review(REGISTER, "| Alice | 12 | 100 | 60 |", 100)
    assert problems and "closest source line" in problems[0] and "| Alice | 12 | 100 | 50 |" in problems[0]
    problems = review(REGISTER, "| Bob | 14 | 300 | - |", 350, name="Bob")
    assert problems and "300" in problems[0] and "null, never 0" in problems[0]


def test_resolve_quote_reports_missing_and_short_fragments():
    source = Source(REGISTER)
    with pytest.raises(QuoteError, match="missing"):
        resolve_quote("", source, "Alice")
    with pytest.raises(QuoteError, match="too short"):
        resolve_quote("| 100 |", source, "Alice")
