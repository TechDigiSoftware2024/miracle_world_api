"""Shared workflow after payment schedule / commission line status changes."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.services.investment_actions import sync_investment_status_with_payment_lines
from app.services.partner_commission_schedule import sync_partner_commission_status_for_month
from app.services.participant_portfolio_recalc import recalc_from_investment_id

from app.utils.supabase_errors import format_api_error

_PS = "payment_schedules"
_BATCH_IN = 100


def _chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def run_after_payment_schedule_row_saved(row: dict) -> None:
    """Sync partner commission lines, investment maturity, and recalc portfolios."""
    iid = str(row.get("investmentId") or "").strip()
    if not iid:
        return
    mn = row.get("monthNumber")
    pst = str(row.get("status") or "").strip().lower()
    if mn is not None and pst:
        sync_partner_commission_status_for_month(iid, int(mn), pst)
    sync_investment_status_with_payment_lines(iid)
    recalc_from_investment_id(iid)


def mark_payment_schedule_paid(schedule_id: int) -> dict:
    """Set payment_schedules row to paid and run full downstream sync."""
    out, _ = mark_payment_schedule_paid_ex(schedule_id)
    return out


def mark_payment_schedule_paid_ex(schedule_id: int) -> tuple[dict, bool]:
    """Set payment_schedules row to paid and return (row, changed_now)."""
    sid = int(schedule_id)
    try:
        cur = supabase.table(_PS).select("*").eq("id", sid).limit(1).execute()
    except APIError as e:
        raise ValueError(format_api_error(e)) from e
    if not cur.data:
        raise ValueError("Payment schedule line not found")
    row = cur.data[0]
    st = str(row.get("status") or "").strip().lower()
    if st == "paid":
        return row, False
    now = datetime.now(timezone.utc).isoformat()
    try:
        updated = (
            supabase.table(_PS)
            .update({"status": "paid", "updatedAt": now})
            .eq("id", sid)
            .execute()
        )
    except APIError as e:
        raise ValueError(format_api_error(e)) from e
    out = updated.data[0] if updated.data else None
    if not out:
        ref = supabase.table(_PS).select("*").eq("id", sid).limit(1).execute()
        out = ref.data[0] if ref.data else None
    if not out:
        raise ValueError("Could not read payment schedule after update")
    run_after_payment_schedule_row_saved(out)
    return out, True


def mark_payment_schedules_paid_batch(
    ordered_ids: list[int],
) -> list[tuple[dict, bool, Optional[str]]]:
    """
    Mark many participant ``payment_schedules`` rows paid in fewer round-trips.

    Returns one tuple ``(row, changed_now, error)`` per input id (same order), matching
    :func:`mark_payment_schedule_paid_ex` semantics for payout aggregation.

    - Rows already ``paid`` → ``changed_now=False``.
    - Invalid status (not pending/due/paid) → no DB update, ``error`` set.
    - Missing id → ``error`` set.
    - After bulk update, runs partner-month sync / investment sync / participant recalc once per
      affected investment (deduped), instead of once per schedule line.
    """
    if not ordered_ids:
        return []

    unique_ids = sorted({int(x) for x in ordered_ids})
    rows_by_id: dict[int, dict] = {}
    for chunk in _chunks(unique_ids, _BATCH_IN):
        try:
            res = supabase.table(_PS).select("*").in_("id", chunk).execute()
        except APIError as e:
            raise ValueError(format_api_error(e)) from e
        for r in res.data or []:
            rows_by_id[int(r["id"])] = r

    results_by_id: dict[int, tuple[dict, bool, Optional[str]]] = {}
    to_patch: list[int] = []
    for sid in unique_ids:
        if sid not in rows_by_id:
            results_by_id[sid] = ({}, False, "Payment schedule line not found")
            continue
        row = rows_by_id[sid]
        st = str(row.get("status") or "").strip().lower()
        if st == "paid":
            results_by_id[sid] = (row, False, None)
        elif st in ("pending", "due"):
            to_patch.append(sid)
        else:
            results_by_id[sid] = (
                row,
                False,
                f"Cannot mark paid (status={row.get('status')})",
            )

    if to_patch:
        now = datetime.now(timezone.utc).isoformat()
        for chunk in _chunks(to_patch, _BATCH_IN):
            try:
                supabase.table(_PS).update({
                    "status": "paid",
                    "updatedAt": now,
                }).in_("id", chunk).execute()
            except APIError as e:
                raise ValueError(format_api_error(e)) from e
        refetched: dict[int, dict] = {}
        for chunk in _chunks(to_patch, _BATCH_IN):
            try:
                res = supabase.table(_PS).select("*").in_("id", chunk).execute()
            except APIError as e:
                raise ValueError(format_api_error(e)) from e
            for r in res.data or []:
                refetched[int(r["id"])] = r
        for sid in to_patch:
            row = refetched.get(sid)
            if not row:
                raise ValueError(f"Could not read payment schedule {sid} after update")
            rows_by_id[sid] = row
            results_by_id[sid] = (row, True, None)

        inv_to_months: dict[str, set[int]] = defaultdict(set)
        for sid in to_patch:
            r0 = rows_by_id[sid]
            iid = str(r0.get("investmentId") or "").strip()
            mn = r0.get("monthNumber")
            if not iid or mn is None:
                continue
            try:
                inv_to_months[iid].add(int(mn))
            except (TypeError, ValueError):
                continue
        for iid in sorted(inv_to_months.keys()):
            for mn in sorted(inv_to_months[iid]):
                sync_partner_commission_status_for_month(iid, mn, "paid")
            sync_investment_status_with_payment_lines(iid)
            recalc_from_investment_id(iid)

    return [results_by_id[sid] for sid in ordered_ids]


def mark_partner_commission_schedules_paid(commission_ids: list[int]) -> list[dict]:
    """
    Set partner_commission_schedules to paid for each line that is still pending/due.

    Lines already ``paid`` are skipped (idempotent batch pay). Returns **only** the rows that
    were updated — pre-update snapshots, suitable for ``recordPayouts`` (no duplicate payouts
    for already-paid lines).
    """
    ids = sorted({int(x) for x in commission_ids if x is not None})
    if not ids:
        return []
    rows: list[dict] = []
    for chunk in _chunks(ids, _BATCH_IN):
        try:
            res = (
                supabase.table("partner_commission_schedules")
                .select("*")
                .in_("id", chunk)
                .execute()
            )
        except APIError as e:
            raise ValueError(format_api_error(e)) from e
        rows.extend(res.data or [])
    if len(rows) != len(ids):
        raise ValueError("One or more partner commission schedule ids were not found")
    to_patch: list[dict] = []
    for r in rows:
        st = str(r.get("status") or "").strip().lower()
        if st in ("pending", "due"):
            to_patch.append(r)
        elif st == "paid":
            continue
        else:
            raise ValueError(
                f"Commission line {r.get('id')} cannot be marked paid (status={r.get('status')})"
            )
    if not to_patch:
        return []
    to_patch_ids = [int(r["id"]) for r in to_patch]
    now = datetime.now(timezone.utc).isoformat()
    try:
        for chunk in _chunks(to_patch_ids, _BATCH_IN):
            supabase.table("partner_commission_schedules").update({
                "status": "paid",
                "updatedAt": now,
            }).in_("id", chunk).execute()
    except APIError as e:
        raise ValueError(format_api_error(e)) from e
    seen_inv: set[str] = set()
    for r in to_patch:
        iid = str(r.get("investmentId") or "").strip()
        if iid and iid not in seen_inv:
            seen_inv.add(iid)
            recalc_from_investment_id(iid)
    return to_patch
