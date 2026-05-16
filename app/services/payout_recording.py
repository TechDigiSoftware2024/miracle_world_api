"""Create paid ``payouts`` rows for schedules/commissions marked paid (mark-paid API)."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.payout_id import new_payout_id
from app.utils.supabase_errors import format_api_error

PARTNER_PAYOUT_AUTO_MERGE_SECONDS = 900
_USER_CHUNK = 50


def _dt_for_payout(val) -> datetime:
    if isinstance(val, datetime):
        d = val
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    s = str(val).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _utc_payout_calendar_date(val) -> date:
    return _dt_for_payout(val).astimezone(timezone.utc).date()


def participant_aggregate_tag(schedule_ids: list[int]) -> str:
    return "aggregated participantScheduleIds=" + ",".join(
        str(i) for i in sorted(set(schedule_ids))
    )


def partner_aggregate_tag(commission_ids: list[int]) -> str:
    return "aggregated commissionScheduleIds=" + ",".join(
        str(i) for i in sorted(set(commission_ids))
    )


def _extract_id_list_from_remarks(remarks: str, *prefixes: str) -> set[str]:
    """Parse comma-separated ids after known remark prefixes (case-insensitive)."""
    blob = str(remarks or "").lower()
    found: set[str] = set()
    for prefix in prefixes:
        pfx = prefix.lower()
        start = 0
        while True:
            idx = blob.find(pfx, start)
            if idx < 0:
                break
            rest = blob[idx + len(pfx) :]
            end = len(rest)
            for sep in (" investmentids=", " aggregated ", ";", "\n"):
                pos = rest.find(sep)
                if pos >= 0:
                    end = min(end, pos)
            for part in rest[:end].split(","):
                part = part.strip()
                if part.isdigit():
                    found.add(part)
            start = idx + len(pfx)
    return found


def schedule_id_covered_in_remarks(remarks: str, schedule_id: int) -> bool:
    sid = str(int(schedule_id))
    ids = _extract_id_list_from_remarks(
        remarks,
        "participantScheduleIds=",
        "aggregated participantScheduleIds=",
    )
    return sid in ids


def commission_id_covered_in_remarks(remarks: str, commission_id: int) -> bool:
    cid = str(int(commission_id))
    ids = _extract_id_list_from_remarks(
        remarks,
        "commissionScheduleIds=",
        "aggregated commissionScheduleIds=",
    )
    return cid in ids


def load_paid_payout_remarks_by_users(
    user_ids: list[str],
    recipient_type: str,
) -> dict[str, str]:
    uids = sorted({str(u).strip() for u in user_ids if str(u).strip()})
    out: dict[str, str] = {}
    if not uids:
        return out
    for i in range(0, len(uids), _USER_CHUNK):
        chunk = uids[i : i + _USER_CHUNK]
        try:
            res = (
                supabase.table("payouts")
                .select("userId, remarks")
                .eq("recipientType", recipient_type)
                .eq("status", "paid")
                .in_("userId", chunk)
                .execute()
            )
        except APIError:
            continue
        for row in res.data or []:
            uid = str(row.get("userId") or "").strip()
            rmk = str(row.get("remarks") or "").lower()
            out[uid] = f"{out.get(uid, '')} {rmk}".strip()
    return out


def remarks_index_has_aggregate_tag(remarks_index: dict[str, str], user_id: str, tag: str) -> bool:
    if not tag:
        return False
    return tag.lower() in remarks_index.get(str(user_id).strip(), "")


def _partner_remarks_have_batch_key(remarks: object) -> bool:
    return "payoutbatchkey=" in str(remarks or "").lower()


def _sanitize_batch_key(k: Optional[str]) -> Optional[str]:
    if k is None:
        return None
    s = str(k).strip()
    if re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", s):
        return s
    return None


def _find_consolidated_partner_payout_row(
    uid: str,
    *,
    batch_key: Optional[str],
    transaction_id: Optional[str],
) -> Optional[dict]:
    uid = str(uid or "").strip()
    if not uid:
        return None
    try:
        if batch_key:
            r = (
                supabase.table("payouts")
                .select("*")
                .eq("userId", uid)
                .eq("recipientType", "partner")
                .eq("status", "paid")
                .ilike("remarks", f"%payoutBatchKey={batch_key}%")
                .order("createdAt", desc=True)
                .limit(1)
                .execute()
            )
            if r.data:
                return r.data[0]
        tid = (transaction_id or "").strip()
        if tid:
            r = (
                supabase.table("payouts")
                .select("*")
                .eq("userId", uid)
                .eq("recipientType", "partner")
                .eq("status", "paid")
                .eq("transactionId", tid)
                .order("createdAt", desc=True)
                .limit(1)
                .execute()
            )
            if r.data:
                return r.data[0]
    except APIError:
        return None
    return None


def _find_recent_partner_payout_for_auto_merge(
    uid: str,
    *,
    payment_method: str,
    payout_date: datetime,
) -> Optional[dict]:
    uid = str(uid or "").strip()
    pm = str(payment_method or "").strip()
    if not uid or not pm:
        return None
    target_day = _utc_payout_calendar_date(payout_date)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=PARTNER_PAYOUT_AUTO_MERGE_SECONDS)
    try:
        r = (
            supabase.table("payouts")
            .select("*")
            .eq("userId", uid)
            .eq("recipientType", "partner")
            .eq("status", "paid")
            .eq("paymentMethod", pm)
            .is_("transactionId", "null")
            .gte("createdAt", cutoff.isoformat())
            .order("createdAt", desc=True)
            .limit(25)
            .execute()
        )
    except APIError:
        return None
    for row in r.data or []:
        if _partner_remarks_have_batch_key(row.get("remarks")):
            continue
        if _utc_payout_calendar_date(row.get("payoutDate")) != target_day:
            continue
        return row
    return None


def _merge_update_partner_payout_row(
    existing: dict,
    *,
    add_amount: float,
    new_payout_date: datetime,
    append_remarks: str,
    payment_method: str,
    transaction_id: Optional[str],
    admin_id: str,
) -> None:
    pid = str(existing.get("payoutId") or "").strip()
    if not pid:
        return
    old_amt = float(existing.get("amount") or 0)
    new_amt = round(old_amt + float(add_amount), 2)
    old_pd = _dt_for_payout(existing.get("payoutDate"))
    max_pd = new_payout_date if new_payout_date > old_pd else old_pd
    pd = max_pd if max_pd.tzinfo else max_pd.replace(tzinfo=timezone.utc)
    remarks = f"{str(existing.get('remarks') or '').strip()} {append_remarks}".strip()
    now = datetime.now(timezone.utc).isoformat()
    body: dict = {
        "amount": new_amt,
        "payoutDate": pd.isoformat(),
        "remarks": remarks,
        "investmentId": None,
        "paymentMethod": payment_method,
        "levelDepth": None,
        "updatedAt": now,
    }
    tid = (transaction_id or "").strip()
    if tid:
        body["transactionId"] = tid
    if admin_id:
        body["createdByAdminId"] = str(admin_id).strip()
    try:
        supabase.table("payouts").update(body).eq("payoutId", pid).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


def _insert_payout_row(
    *,
    user_id: str,
    recipient_type: str,
    amount: float,
    investment_id: Optional[str],
    payout_date: datetime,
    payout_type: str,
    payment_method: str,
    transaction_id: Optional[str],
    remarks: str,
    level_depth: Optional[int],
    admin_id: str,
) -> None:
    pid = new_payout_id()
    pd = payout_date if payout_date.tzinfo else payout_date.replace(tzinfo=timezone.utc)
    body = {
        "payoutId": pid,
        "userId": str(user_id).strip(),
        "recipientType": recipient_type,
        "amount": round(float(amount), 2),
        "status": "paid",
        "paymentMethod": payment_method,
        "transactionId": transaction_id,
        "investmentId": str(investment_id).strip() if investment_id else None,
        "payoutDate": pd.isoformat(),
        "remarks": remarks or "",
        "payoutType": payout_type,
        "createdBy": "automatic",
        "createdByAdminId": (str(admin_id).strip() if admin_id else None),
        "levelDepth": level_depth,
        "updatedAt": None,
    }
    if recipient_type == "participant":
        body["levelDepth"] = None
    try:
        supabase.table("payouts").insert(body).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


def record_participant_payouts(
    *,
    by_participant: dict[str, list[tuple[int, dict, str]]],
    paid_remarks_index: dict[str, str],
    payment_method: str,
    transaction_id: Optional[str],
    base_remarks: str,
    admin_id: str,
) -> int:
    """One paid payout per participantId; skips rows already tagged in remarks."""
    recorded = 0
    for uid, items in by_participant.items():
        uncovered = [
            t
            for t in items
            if not schedule_id_covered_in_remarks(paid_remarks_index.get(uid, ""), t[0])
        ]
        if not uncovered:
            continue
        sids = [t[0] for t in uncovered]
        tag = participant_aggregate_tag(sids)
        if remarks_index_has_aggregate_tag(paid_remarks_index, uid, tag):
            continue
        total_amt = sum(float(t[1].get("amount") or 0) for t in uncovered)
        max_pd = max(_dt_for_payout(t[1].get("payoutDate")) for t in uncovered)
        iids = sorted({t[2] for t in uncovered if t[2]})
        inv_single: Optional[str] = iids[0] if len(iids) == 1 else None
        rmk = (base_remarks or "").strip()
        rmk = f"{rmk} {tag} investmentIds={','.join(iids)}".strip()
        _insert_payout_row(
            user_id=uid,
            recipient_type="participant",
            amount=total_amt,
            investment_id=inv_single,
            payout_date=max_pd,
            payout_type="monthly_income",
            payment_method=payment_method,
            transaction_id=transaction_id,
            remarks=rmk,
            level_depth=None,
            admin_id=admin_id,
        )
        paid_remarks_index[uid] = f"{paid_remarks_index.get(uid, '')} {tag.lower()}".strip()
        recorded += 1
    return recorded


def record_partner_payouts(
    *,
    by_beneficiary: dict[str, list[dict]],
    paid_remarks_index: dict[str, str],
    payment_method: str,
    transaction_id: Optional[str],
    base_remarks: str,
    admin_id: str,
    batch_key: Optional[str],
) -> int:
    recorded = 0
    batch_key = _sanitize_batch_key(batch_key)
    txn_for_merge = (transaction_id or "").strip() or None
    for uid, all_rows in by_beneficiary.items():
        uncovered = [
            r
            for r in all_rows
            if not commission_id_covered_in_remarks(
                paid_remarks_index.get(uid, ""), int(r["id"])
            )
        ]
        if not uncovered:
            continue
        cids = [int(r["id"]) for r in uncovered]
        tag = partner_aggregate_tag(cids)
        if remarks_index_has_aggregate_tag(paid_remarks_index, uid, tag):
            continue
        total_amt = sum(float(r.get("amount") or 0) for r in uncovered)
        max_pd = max(_dt_for_payout(r.get("payoutDate")) for r in uncovered)
        levels = {int(r.get("level") or 0) for r in uncovered}
        level_depth: Optional[int] = None
        if len(levels) == 1:
            ld0 = next(iter(levels))
            level_depth = ld0 if ld0 >= 1 else None
        iids = sorted(
            {
                str(r.get("investmentId") or "").strip()
                for r in uncovered
                if str(r.get("investmentId") or "").strip()
            }
        )
        inv_single = iids[0] if len(iids) == 1 else None
        rmk = (base_remarks or "").strip()
        rmk = f"{rmk} {tag} investmentIds={','.join(iids)}".strip()
        if batch_key:
            rmk = f"{rmk} payoutBatchKey={batch_key}".strip()
        exist = _find_consolidated_partner_payout_row(
            uid, batch_key=batch_key, transaction_id=txn_for_merge
        )
        if not exist and batch_key is None and txn_for_merge is None:
            exist = _find_recent_partner_payout_for_auto_merge(
                uid, payment_method=payment_method, payout_date=max_pd
            )
        if exist:
            _merge_update_partner_payout_row(
                exist,
                add_amount=total_amt,
                new_payout_date=max_pd,
                append_remarks=rmk,
                payment_method=payment_method,
                transaction_id=txn_for_merge,
                admin_id=admin_id,
            )
        else:
            _insert_payout_row(
                user_id=uid,
                recipient_type="partner",
                amount=total_amt,
                investment_id=inv_single,
                payout_date=max_pd,
                payout_type="commission",
                payment_method=payment_method,
                transaction_id=transaction_id,
                remarks=rmk,
                level_depth=level_depth,
                admin_id=admin_id,
            )
        paid_remarks_index[uid] = f"{paid_remarks_index.get(uid, '')} {tag.lower()}".strip()
        recorded += 1
    return recorded


def build_participant_payout_groups(
    schedule_rows: list[tuple[int, dict, Optional[str]]],
    inv_to_participant: dict[str, str],
) -> dict[str, list[tuple[int, dict, str]]]:
    """Group paid schedule lines by participantId for payout insert."""
    acc: dict[str, list[tuple[int, dict, str]]] = defaultdict(list)
    for psid, row, err in schedule_rows:
        if err:
            continue
        if str(row.get("status") or "").strip().lower() != "paid":
            continue
        iid = str(row.get("investmentId") or "").strip()
        uid = inv_to_participant.get(iid, "").strip()
        if not uid:
            continue
        acc[uid].append((psid, row, iid))
    return acc


def build_partner_payout_groups(
    commission_rows: list[dict],
) -> dict[str, list[dict]]:
    by_ben: dict[str, list[dict]] = defaultdict(list)
    for r in commission_rows:
        if str(r.get("status") or "").strip().lower() != "paid":
            continue
        uid = str(r.get("beneficiaryPartnerId") or "").strip()
        if uid:
            by_ben[uid].append(r)
    return by_ben
