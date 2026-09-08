"""Stage 6: deterministic validation checks over extracted cap-table facts.

Every check is pure Python; violations become structured findings, never
silent corrections (design §2.1 stage 6).
"""

from __future__ import annotations

from typing import Any

from lib.captable.aggregation import names_match, normalize_lender_name

TOLERANCE = 0.005  # 0.5 %


def _finding(check: str, status: str, severity: str, detail: str) -> dict:
    return {
        "check": check,
        "status": status,
        "severity": severity,
        "detail": detail,
    }


def _value(entry: Any) -> Any:
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def _holdings_sum(stakeholder: dict) -> float:
    return sum(
        h.get("count") or 0.0 for h in stakeholder.get("holdings", [])
    )


def check_issued_totals(captable: dict) -> list[dict]:
    """Sum of extracted holdings per class matches the table's totals."""
    findings = []
    sums: dict[str, float] = {}
    for stakeholder in captable.get("stakeholders", []):
        for holding in stakeholder.get("holdings", []):
            class_id = holding.get("class_id")
            sums[class_id] = sums.get(class_id, 0.0) + (
                holding.get("count") or 0.0
            )
    for total in (captable.get("totals") or {}).get("by_class", []):
        class_id, stated = total.get("class_id"), total.get("issued_total")
        if not stated:
            continue
        extracted = sums.get(class_id, 0.0)
        ok = abs(extracted - stated) / stated <= TOLERANCE
        findings.append(
            _finding(
                f"issued_total_{class_id}",
                "pass" if ok else "fail",
                "info" if ok else "high",
                f"extracted {extracted:,.0f} vs stated {stated:,.0f}",
            )
        )
    return findings


def check_diluted_equation(captable: dict) -> list[dict]:
    """diluted_total = issued - treasury + option/pool deltas."""
    totals = captable.get("totals") or {}
    diluted_total = totals.get("diluted_total")
    if not diluted_total:
        return [
            _finding(
                "diluted_equation",
                "skipped",
                "info",
                "No fully-diluted total stated in the source.",
            )
        ]
    issued = sum(
        t.get("issued_total") or 0.0 for t in totals.get("by_class", [])
    )
    treasury = sum(
        _holdings_sum(s)
        for s in captable.get("stakeholders", [])
        if s.get("kind") == "treasury"
    )
    deltas = 0.0
    for stakeholder in captable.get("stakeholders", []):
        if stakeholder.get("kind") == "treasury":
            continue
        diluted = stakeholder.get("diluted_count")
        if diluted is None:
            continue
        deltas += max(0.0, diluted - _holdings_sum(stakeholder))
    expected = issued - treasury + deltas
    ok = abs(expected - diluted_total) / diluted_total <= TOLERANCE
    return [
        _finding(
            "diluted_equation",
            "pass" if ok else "fail",
            "info" if ok else "high",
            f"issued {issued:,.0f} - treasury {treasury:,.0f} + "
            f"options/pools {deltas:,.0f} = {expected:,.0f} vs stated "
            f"diluted total {diluted_total:,.0f}",
        )
    ]


def _source_as_of(source: dict | None) -> str | None:
    from lib.captable.snapshot import normalize_iso_date

    entry = (source or {}).get("as_of_date")
    value = entry.get("value") if isinstance(entry, dict) else entry
    return normalize_iso_date(value) if isinstance(value, str) else None


def _dates_differ(a: str | None, b: str | None) -> bool:
    return bool(a and b and a[:7] != b[:7])  # different month = skew


def check_diluted_rowsum(captable: dict) -> list[dict]:
    """Sum of per-holder diluted counts matches the stated diluted total.

    Note the scope honestly: this sums the EXTRACTED holder set, so it
    catches extraction-internal inconsistencies (dropped or double-counted
    rows vs the stated total). Merges the extractor performed on source
    rows are disclosed via the extraction's own `assumptions`, not here.
    """
    totals = captable.get("totals") or {}
    diluted_total = totals.get("diluted_total")
    if not diluted_total:
        return []
    rowsum = 0.0
    for stakeholder in captable.get("stakeholders", []):
        if stakeholder.get("kind") == "treasury":
            continue
        diluted = stakeholder.get("diluted_count")
        rowsum += (
            diluted if diluted is not None else _holdings_sum(stakeholder)
        )
    ok = abs(rowsum - diluted_total) / diluted_total <= TOLERANCE
    return [
        _finding(
            "diluted_rowsum",
            "pass" if ok else "fail",
            "info" if ok else "high",
            f"sum of holder diluted counts {rowsum:,.0f} vs stated "
            f"diluted total {diluted_total:,.0f}"
            + (
                ""
                if ok
                else " — rows were dropped, double-counted, or a pool "
                "line was merged without disclosure"
            ),
        )
    ]


def check_register_reconciliation(
    captable: dict, register: dict | None
) -> list[dict]:
    """Register current holdings match the cap table per shareholder.

    When the register and the cap table speak as of different dates, a
    count difference may be a legitimate transfer in between — mismatches
    are then reported at medium severity with the date gap stated, never
    as hard highs.
    """
    if not register:
        return [
            _finding(
                "register_reconciliation",
                "skipped",
                "medium",
                "No share register in the data room — the cap table cannot "
                "be reconciled against the legal register.",
            )
        ]
    findings = []
    register_as_of = _source_as_of(register)
    captable_as_of = _source_as_of(captable)
    skewed = _dates_differ(register_as_of, captable_as_of)
    skew_note = (
        f" [register as of {register_as_of} vs cap table as of "
        f"{captable_as_of} — the difference may be a legitimate transfer "
        "between those dates; reconcile against a same-dated cap table]"
        if skewed
        else ""
    )
    mismatch_severity = "medium" if skewed else "high"
    cap_by_name: dict[str, dict[str, float]] = {}
    for stakeholder in captable.get("stakeholders", []):
        key = normalize_lender_name(stakeholder.get("name", ""))
        row = cap_by_name.setdefault(key, {})
        for holding in stakeholder.get("holdings", []):
            row[holding.get("class_id")] = row.get(
                holding.get("class_id"), 0.0
            ) + (holding.get("count") or 0.0)

    mismatches = 0
    matched = 0
    for entry in register.get("entries", []):
        key = normalize_lender_name(entry.get("name", ""))
        cap_row = None
        for cap_key, row in cap_by_name.items():
            if names_match(key, cap_key):
                cap_row = row
                break
        if cap_row is None:
            findings.append(
                _finding(
                    "register_only_holder",
                    "fail",
                    "medium",
                    f"{entry.get('name')!r} appears in the register but "
                    "not in the cap table.",
                )
            )
            continue
        hinted = {
            class_id
            for class_id in cap_row
            if "common" in (class_id or "").lower()
            or "preferred" in (class_id or "").lower()
            or "stamm" in (class_id or "").lower()
            or "vorzug" in (class_id or "").lower()
        }
        hints_usable = hinted == set(cap_row)
        if not hints_usable:
            # Class ids don't map onto common/preferred vocabulary —
            # reconcile the holder's TOTAL shares instead of guessing.
            register_total = sum(
                entry.get(f) or 0.0
                for f in ("current_common", "current_preferred")
            )
            cap_total = sum(cap_row.values())
            if abs(cap_total - register_total) > max(
                1.0, register_total * TOLERANCE
            ):
                mismatches += 1
                findings.append(
                    _finding(
                        "register_mismatch",
                        "fail",
                        mismatch_severity,
                        f"{entry.get('name')!r} total shares: register "
                        f"{register_total:,.0f} vs cap table "
                        f"{cap_total:,.0f} (class ids not mappable to "
                        f"common/preferred; totals compared){skew_note}",
                    )
                )
            else:
                matched += 1
            continue
        for register_field, class_hint in (
            ("current_common", ("common", "stamm")),
            ("current_preferred", ("preferred", "vorzug")),
        ):
            register_count = entry.get(register_field)
            if register_count is None:
                continue
            cap_count = sum(
                count
                for class_id, count in cap_row.items()
                if any(h in (class_id or "").lower() for h in class_hint)
            )
            if abs(cap_count - register_count) > max(
                1.0, register_count * TOLERANCE
            ):
                mismatches += 1
                findings.append(
                    _finding(
                        "register_mismatch",
                        "fail",
                        mismatch_severity,
                        f"{entry.get('name')!r} {register_field}: register "
                        f"{register_count:,.0f} vs cap table "
                        f"{cap_count:,.0f}{skew_note}",
                    )
                )
            else:
                matched += 1
    holder_count = sum(
        1
        for s in captable.get("stakeholders", [])
        if s.get("kind") in ("individual", "entity")
    )
    coverage_note = (
        f" Register covers {len(register.get('entries', []))} holders vs "
        f"{holder_count} individual/entity holders in the cap table."
        if len(register.get("entries", [])) < holder_count
        else ""
    )
    findings.append(
        _finding(
            "register_reconciliation",
            "pass" if mismatches == 0 else "fail",
            "info" if mismatches == 0 else mismatch_severity,
            f"{matched} holdings reconciled, {mismatches} mismatches."
            f"{skew_note}{coverage_note}",
        )
    )
    return findings


def check_pool_consistency(
    captable: dict, pool_docs: list[dict]
) -> list[dict]:
    """Pool figures agree across the cap table and pool documents."""
    # Compare pools by identity, not as bags of floats. Exact kinds pair
    # directly; sources often label the same economic pool differently
    # ("grantable" vs "esop"), so within the employee-equity family a
    # cross-kind pair is made only when each source has exactly ONE pool in
    # that family (unambiguous). One-sided coverage is a note, never a
    # contradiction.
    employee_family = {"esop", "psop", "grantable", "authorized_capital"}

    def family(kind: str) -> str:
        return "employee" if kind in employee_family else kind

    per_source: dict[str, dict[str, float]] = {}
    for pool in captable.get("pools", []):
        if pool.get("total") is not None:
            per_source.setdefault("captable", {})[
                pool.get("kind") or "other"
            ] = pool["total"]
    for doc in pool_docs:
        for pool in doc.get("pools", []):
            if pool.get("total") is not None:
                per_source.setdefault(doc.get("document", "?"), {})[
                    pool.get("kind") or "other"
                ] = pool["total"]

    def comparable_pairs():
        sources = list(per_source.items())
        for i, (source_a, pools_a) in enumerate(sources):
            for source_b, pools_b in sources[i + 1 :]:
                for kind in set(pools_a) & set(pools_b):
                    yield (kind, source_a, pools_a[kind],
                           source_b, pools_b[kind])
                fam_a = {
                    k: v for k, v in pools_a.items()
                    if family(k) == "employee" and k not in pools_b
                }
                fam_b = {
                    k: v for k, v in pools_b.items()
                    if family(k) == "employee" and k not in pools_a
                }
                if len(fam_a) == 1 and len(fam_b) == 1:
                    (kind_a, val_a), = fam_a.items()
                    (kind_b, val_b), = fam_b.items()
                    yield (f"{kind_a}~{kind_b}", source_a, val_a,
                           source_b, val_b)

    pairs = list(comparable_pairs())
    if not pairs:
        return [
            _finding(
                "pool_consistency",
                "skipped",
                "info",
                "No pool is comparably reported by two or more sources.",
            )
        ]
    conflicts = [
        f"{kind}: {source_a}={val_a:,.0f} vs {source_b}={val_b:,.0f}"
        for kind, source_a, val_a, source_b, val_b in pairs
        if abs(val_a - val_b) > max(1.0, val_a * TOLERANCE)
    ]
    if conflicts:
        captable_as_of = _source_as_of(captable)
        doc_dates = {
            doc.get("document", "?"): _source_as_of(doc) for doc in pool_docs
        }
        skewed = any(
            _dates_differ(captable_as_of, doc_date)
            for doc_date in doc_dates.values()
        )
        dates_text = ", ".join(
            f"{doc} as of {doc_date or 'unknown'}"
            for doc, doc_date in doc_dates.items()
        )
        skew_note = (
            f" [sources speak as of different dates: cap table as of "
            f"{captable_as_of}, {dates_text} — the difference may reflect "
            "grants between those dates]"
            if skewed
            else ""
        )
        return [
            _finding(
                "pool_consistency",
                "fail",
                "medium" if skewed else "high",
                "Pool totals disagree across sources: "
                + "; ".join(conflicts)
                + ". No reliable pool ledger; request the grant register."
                + skew_note,
            )
        ]
    return [
        _finding(
            "pool_consistency",
            "pass",
            "info",
            f"{len(pairs)} pool figure"
            + ("s" if len(pairs) != 1 else "")
            + " agree"
            + ("" if len(pairs) != 1 else "s")
            + " across sources.",
        )
    ]


def check_cla_lifecycle(
    captable: dict,
    register: dict | None,
    clas: list[dict],
) -> list[dict]:
    """Lender-is-shareholder: distinguish insider bridge from conversion."""
    findings = []
    shareholder_keys = {
        normalize_lender_name(s.get("name", ""))
        for s in captable.get("stakeholders", [])
    }
    acquisition_by_name = {}
    for entry in (register or {}).get("entries", []):
        acquisition_by_name[
            normalize_lender_name(entry.get("name", ""))
        ] = entry.get("first_acquisition_date")
    for cla in clas:
        if cla.get("status") != "executed":
            continue
        execution = _value(cla.get("execution_date"))
        for lender in cla.get("lenders", []):
            key = normalize_lender_name(lender.get("name", ""))
            if not any(names_match(key, s) for s in shareholder_keys):
                continue
            acquired = acquisition_by_name.get(key)
            if acquired is None:
                for reg_key, reg_date in acquisition_by_name.items():
                    if names_match(key, reg_key):
                        acquired = reg_date
                        break
            from lib.captable.aggregation import _parse_date

            acquired_date = _parse_date(acquired)
            execution_date = _parse_date(execution)
            if (
                acquired_date
                and execution_date
                and acquired_date > execution_date
            ):
                findings.append(
                    _finding(
                        "cla_possibly_converted",
                        "warn",
                        "medium",
                        f"Lender {lender.get('name')!r} acquired shares "
                        f"({acquired}) after the CLA execution "
                        f"({execution}) — verify whether the loan "
                        "converted (it may be misreported as outstanding).",
                    )
                )
            else:
                findings.append(
                    _finding(
                        "cla_lender_is_shareholder",
                        "info",
                        "info",
                        f"Lender {lender.get('name')!r} is also a "
                        "shareholder — consistent with an insider bridge "
                        "loan; verify pre-existing vs converted.",
                    )
                )
    return findings


def check_nominal_floor(captable: dict, clas: list[dict]) -> list[dict]:
    """A cap-implied conversion price below nominal value is impossible."""
    findings = []
    diluted_total = (captable.get("totals") or {}).get("diluted_total")
    nominals = [
        c.get("nominal_value")
        for c in captable.get("share_classes", [])
        if c.get("nominal_value")
    ]
    if not diluted_total or not nominals:
        return findings
    min_nominal = min(nominals)
    for cla in clas:
        cap = _value(cla.get("valuation_cap"))
        if cap is None:
            continue
        implied = cap / diluted_total
        if implied < min_nominal:
            findings.append(
                _finding(
                    "nominal_floor",
                    "fail",
                    "severe",
                    f"{cla.get('document')}: cap-implied price "
                    f"{implied:.4f} is below the nominal value "
                    f"{min_nominal} (art. 624 CO) — conversion requires a "
                    "share split or nominal reduction first.",
                )
            )
    return findings


def check_cross_snapshot(previous: dict, current: dict) -> list[dict]:
    """Event-style consistency between two snapshots (design §2.3)."""
    findings = []
    prev_totals = {
        t.get("class_id"): t.get("issued_total")
        for t in (previous.get("totals") or {}).get("by_class", [])
    }
    curr_totals = {
        t.get("class_id"): t.get("issued_total")
        for t in (current.get("totals") or {}).get("by_class", [])
    }
    for class_id, prev_count in prev_totals.items():
        curr_count = curr_totals.get(class_id) or 0.0
        if prev_count and curr_count < prev_count:
            findings.append(
                _finding(
                    "shrinking_share_class",
                    "fail",
                    "high",
                    f"{class_id}: {prev_count:,.0f} -> {curr_count:,.0f} "
                    "without an evidenced split/cancellation.",
                )
            )
    prev_holders = {
        normalize_lender_name(s.get("name", "")): _holdings_sum(s)
        for s in previous.get("stakeholders", [])
    }
    for stakeholder in current.get("stakeholders", []):
        key = normalize_lender_name(stakeholder.get("name", ""))
        prev_sum = prev_holders.get(key)
        if prev_sum and _holdings_sum(stakeholder) < prev_sum - 0.5:
            findings.append(
                _finding(
                    "shrinking_holder",
                    "warn",
                    "medium",
                    f"{stakeholder.get('name')!r}: "
                    f"{prev_sum:,.0f} -> {_holdings_sum(stakeholder):,.0f}; "
                    "no transfer document identified in the data room (the "
                    "counterparty may be visible on the cap table itself — "
                    "verify and request the transfer agreement).",
                )
            )
    return findings


def validate_captable(
    captable: dict,
    *,
    register: dict | None = None,
    pool_docs: list[dict] | None = None,
    clas: list[dict] | None = None,
    register_captable: dict | None = None,
    pool_captable: dict | None = None,
) -> list[dict]:
    """Run all single-snapshot checks.

    ``register_captable``/``pool_captable`` let the caller reconcile the
    register and pool documents against the cap-table version NEAREST
    their own as-of dates (root-cause fix for date-skew artifacts); they
    default to the primary (latest) cap table.
    """
    findings = []
    findings += check_issued_totals(captable)
    findings += check_diluted_equation(captable)
    findings += check_diluted_rowsum(captable)
    findings += check_register_reconciliation(
        register_captable or captable, register
    )
    findings += check_pool_consistency(
        pool_captable or captable, pool_docs or []
    )
    findings += check_cla_lifecycle(captable, register, clas or [])
    findings += check_nominal_floor(captable, clas or [])
    return findings
