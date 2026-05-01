"""Closing / payout export report: date filters, user enrichment, bank details."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.schemas.closing_reports_admin import (
    BankDetailsExportBlock,
    ClosingPayoutReportResponse,
    ClosingPayoutRow,
    ClosingPayoutSummary,
)
from app.utils.db_column_names import camel_partner_pk_column, camel_participant_pk_column

_BANK = "bank_details"


def _parse_yyyy_mm_dd(s: str) -> tuple[int, int, int]:
    parts = (s or "").strip()[:10].split("-")
    if len(parts) != 3:
        raise ValueError("expected YYYY-MM-DD")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _month_range_utc(year: int, month: int) -> tuple[datetime, datetime]:
    last = calendar.monthrange(year, month)[1]
    lo = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    hi = datetime(year, month, last, 23, 59, 59, tzinfo=timezone.utc)
    return lo, hi


def _day_range_utc(y: int, m: int, d: int) -> tuple[datetime, datetime]:
    lo = datetime(y, m, d, 0, 0, 0, tzinfo=timezone.utc)
    hi = datetime(y, m, d, 23, 59, 59, tzinfo=timezone.utc)
    return lo, hi


def _bank_block_from_row(r: Optional[dict]) -> Optional[BankDetailsExportBlock]:
    if not r:
        return None
    return BankDetailsExportBlock(
        holderName=str(r.get("holderName") or ""),
        bankName=str(r.get("bankName") or ""),
        accountNumber=str(r.get("accountNumber") or ""),
        ifscCode=str(r.get("ifscCode") or ""),
        upiId=str(r.get("upiId") or ""),
        branchName=str(r.get("branchName") or ""),
        accountType=str(r.get("accountType") or ""),
        status=str(r.get("status") or ""),
    )


def build_closing_payout_report(
    *,
    payout_date: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    payout_date_from: Optional[str] = None,
    payout_date_to: Optional[str] = None,
    recipient_type: str = "all",
    user_id: Optional[str] = None,
    name_query: Optional[str] = None,
    payout_status: str = "paid",
) -> ClosingPayoutReportResponse:
    """
    At least one date scope is required: ``payoutDate``, or ``year``+``month``, or a from/to range.
    """
    lo: Optional[datetime] = None
    hi: Optional[datetime] = None

    if payout_date and str(payout_date).strip():
        y, m, d = _parse_yyyy_mm_dd(str(payout_date))
        lo, hi = _day_range_utc(y, m, d)
    elif year is not None and month is not None:
        if not (1 <= int(month) <= 12):
            raise ValueError("month must be 1–12")
        lo, hi = _month_range_utc(int(year), int(month))
    elif payout_date_from or payout_date_to:
        if payout_date_from:
            y, m, d = _parse_yyyy_mm_dd(str(payout_date_from))
            lo = datetime(y, m, d, 0, 0, 0, tzinfo=timezone.utc)
        if payout_date_to:
            y2, m2, d2 = _parse_yyyy_mm_dd(str(payout_date_to))
            hi = datetime(y2, m2, d2, 23, 59, 59, tzinfo=timezone.utc)
        if lo is None:
            lo = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        if hi is None:
            hi = datetime(2100, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    else:
        raise ValueError(
            "Provide payoutDate (single day), or year+month (calendar month), "
            "or payoutDateFrom and payoutDateTo"
        )

    try:
        q = supabase.table("payouts").select("*")
        if recipient_type and str(recipient_type).strip().lower() not in ("", "all"):
            q = q.eq("recipientType", str(recipient_type).strip())
        if payout_status and str(payout_status).strip():
            q = q.eq("status", str(payout_status).strip())
        if user_id and str(user_id).strip():
            q = q.eq("userId", str(user_id).strip())
        q = q.gte("payoutDate", lo.isoformat()).lte("payoutDate", hi.isoformat())
        res = q.order("payoutDate", desc=True).order("createdAt", desc=True).execute()
    except APIError as e:
        raise ValueError(str(e)) from e

    rows_raw: list[dict] = list(res.data or [])

    name_pat = (name_query or "").strip()
    allowed_ids: Optional[set[str]] = None
    if name_pat:
        p_pk = camel_participant_pk_column()
        a_pk = camel_partner_pk_column()
        try:
            pr = supabase.table("participants").select(p_pk).ilike("name", f"%{name_pat}%").execute()
            ar = supabase.table("partners").select(a_pk).ilike("name", f"%{name_pat}%").execute()
        except APIError as e:
            raise ValueError(str(e)) from e
        allowed_ids = set()
        for r in pr.data or []:
            allowed_ids.add(str(r.get(p_pk) or "").strip())
        for r in ar.data or []:
            allowed_ids.add(str(r.get(a_pk) or "").strip())
        allowed_ids.discard("")
        rows_raw = [r for r in rows_raw if str(r.get("userId") or "").strip() in allowed_ids]

    uids = sorted({str(r.get("userId") or "").strip() for r in rows_raw})
    uids = [u for u in uids if u]

    p_pk = camel_participant_pk_column()
    a_pk = camel_partner_pk_column()
    part_by_id: dict[str, dict] = {}
    par_by_id: dict[str, dict] = {}
    bank_by_uid: dict[str, dict] = {}

    for i in range(0, len(uids), 80):
        chunk = uids[i : i + 80]
        try:
            p1 = supabase.table("participants").select(f"{p_pk},name,phone,email").in_(p_pk, chunk).execute()
            for r in p1.data or []:
                part_by_id[str(r.get(p_pk) or "")] = r
        except APIError:
            pass
        try:
            p2 = supabase.table("partners").select(f"{a_pk},name,phone,email").in_(a_pk, chunk).execute()
            for r in p2.data or []:
                par_by_id[str(r.get(a_pk) or "")] = r
        except APIError:
            pass
        try:
            b = supabase.table(_BANK).select("*").in_("userId", chunk).execute()
            for r in b.data or []:
                bank_by_uid[str(r.get("userId") or "").strip()] = r
        except APIError:
            pass

    out_rows: list[ClosingPayoutRow] = []
    amt_p = 0.0
    amt_a = 0.0
    for r in rows_raw:
        uid = str(r.get("userId") or "").strip()
        rt = str(r.get("recipientType") or "").strip()
        nm = ""
        phone = ""
        contact = ""
        part = part_by_id.get(uid)
        par = par_by_id.get(uid)
        if rt == "participant" and part:
            nm = str(part.get("name") or "")
            phone = str(part.get("phone") or "")
            contact = str(part.get("email") or "")
        elif rt == "partner" and par:
            nm = str(par.get("name") or "")
            phone = str(par.get("phone") or "")
            contact = str(par.get("email") or "")
        else:
            nm = uid
        amt = float(r.get("amount") or 0)
        if rt == "participant":
            amt_p += amt
        else:
            amt_a += amt
        out_rows.append(
            ClosingPayoutRow(
                payoutId=str(r.get("payoutId") or ""),
                userId=uid,
                recipientType=rt,
                displayName=nm,
                phone=phone,
                emailOrContact=contact,
                amount=round(amt, 2),
                payoutDate=_coerce_dt(r.get("payoutDate")),
                status=str(r.get("status") or ""),
                paymentMethod=str(r.get("paymentMethod") or ""),
                transactionId=r.get("transactionId"),
                payoutType=str(r.get("payoutType") or ""),
                investmentId=(
                    str(inv).strip()
                    if (inv := r.get("investmentId")) not in (None, "")
                    else None
                ),
                remarks=str(r.get("remarks") or ""),
                bankDetails=_bank_block_from_row(bank_by_uid.get(uid)),
            )
        )

    unique_users = len({r.user_id for r in out_rows})
    summary = ClosingPayoutSummary(
        payoutCount=len(out_rows),
        uniqueUsers=unique_users,
        totalAmount=round(amt_p + amt_a, 2),
        amountParticipants=round(amt_p, 2),
        amountPartners=round(amt_a, 2),
    )
    return ClosingPayoutReportResponse(summary=summary, rows=out_rows)


def _coerce_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        d = val
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    s = str(val).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
