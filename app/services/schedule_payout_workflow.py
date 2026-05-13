"""Shared workflow after payment schedule / commission line status changes."""

from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.services.investment_actions import sync_investment_status_with_payment_lines
from app.services.partner_commission_schedule import sync_partner_commission_status_for_month
from app.services.participant_portfolio_recalc import recalc_from_investment_id

from app.utils.supabase_errors import format_api_error

_PS = "payment_schedules"


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
    try:
        res = (
            supabase.table("partner_commission_schedules")
            .select("*")
            .in_("id", ids)
            .execute()
        )
    except APIError as e:
        raise ValueError(format_api_error(e)) from e
    rows = list(res.data or [])
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
        supabase.table("partner_commission_schedules").update({
            "status": "paid",
            "updatedAt": now,
        }).in_("id", to_patch_ids).execute()
    except APIError as e:
        raise ValueError(format_api_error(e)) from e
    seen_inv: set[str] = set()
    for r in to_patch:
        iid = str(r.get("investmentId") or "").strip()
        if iid and iid not in seen_inv:
            seen_inv.add(iid)
            recalc_from_investment_id(iid)
    return to_patch
