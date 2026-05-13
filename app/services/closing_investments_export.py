"""
Closing-month investment export: JSON aligned with admin Excel (full hierarchy,
by investment, by partner, monthly 4-sheet pack) including TDS and bank_details.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.utils.db_column_names import camel_partner_pk_column, camel_participant_pk_column
from app.utils.phone_normalize import normalize_phone_digits

_BANK = "bank_details"
_INV = "investments"
_PS = "payment_schedules"
_PC = "partner_commission_schedules"
_PAGE = 1000


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


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


def _payout_in_utc_month(val: Any, year: int, month: int) -> bool:
    d = _coerce_dt(val)
    return d.year == int(year) and d.month == int(month)


def _schedule_lines_in_utc_month(lines: list[dict], y: int, mo: int) -> list[dict]:
    """All schedule rows whose payoutDate falls in the closing calendar month (any status)."""
    return [ln for ln in lines if _payout_in_utc_month(ln.get("payoutDate"), y, mo)]


def _rollup_participant_month_amount_status(month_lines: list[dict]) -> tuple[float, str, str]:
    """
    Sum amounts for all participant lines in the month (paid, due, pending all included).
    Returns (total_amount, payout_date_iso, status_label).
    """
    if not month_lines:
        return 0.0, "", ""
    amt = round(sum(_f(ln.get("amount")) for ln in month_lines), 2)
    sorted_ln = sorted(month_lines, key=lambda x: _coerce_dt(x.get("payoutDate")))
    d0 = _coerce_dt(sorted_ln[0].get("payoutDate")).date().isoformat()
    lowered = {
        str(ln.get("status") or "").strip().lower()
        for ln in month_lines
        if str(ln.get("status") or "").strip()
    }
    if len(lowered) == 1:
        st = str(sorted_ln[0].get("status") or "")
    elif len(lowered) > 1:
        st = "mixed"
    else:
        st = ""
    return amt, d0, st


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    """Return date from YYYY-MM-DD or None."""
    if not s or not str(s).strip():
        return None
    parts = str(s).strip()[:10].split("-")
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return datetime(y, m, d, tzinfo=timezone.utc).date()
    except ValueError:
        return None


def _partner_id_matches_agent_query(aid: str, par_by_id: dict, agent_query: str) -> bool:
    qraw = (agent_query or "").strip()
    if not qraw:
        return True
    q = qraw.lower()
    q_digits = normalize_phone_digits(qraw) if any(c.isdigit() for c in qraw) else ""
    rec = par_by_id.get(aid) or {}
    nm = str(rec.get("name") or "").lower()
    pid = aid.lower()
    ph = normalize_phone_digits(str(rec.get("phone") or ""))
    if q in nm or q in pid:
        return True
    if len(q_digits) >= 10 and ph == q_digits:
        return True
    if len(q_digits) >= 4 and q_digits in ph and len(ph) >= 10:
        return True
    return False


def _investment_matches_agent_query(
    inv: dict,
    pc_lines: list[dict],
    par_by_id: dict,
    agent_query: str,
) -> bool:
    qraw = (agent_query or "").strip()
    if not qraw:
        return True
    cand_ids: set[str] = set()
    ag = str(inv.get("agentId") or "").strip()
    if ag:
        cand_ids.add(ag)
    for row in pc_lines:
        bid = str(row.get("beneficiaryPartnerId") or "").strip()
        if bid:
            cand_ids.add(bid)
    for aid in cand_ids:
        if _partner_id_matches_agent_query(aid, par_by_id, qraw):
            return True
    return False


def _apply_closing_investment_filters(
    investments: list[dict],
    *,
    pc_by_inv: dict[str, list[dict]],
    part_by_id: dict,
    par_by_id: dict,
    investment_date_from: Optional[str] = None,
    investment_date_to: Optional[str] = None,
    fund_type: Optional[str] = None,
    location: Optional[str] = None,
    participant_search: Optional[str] = None,
    agent_query: Optional[str] = None,
) -> list[dict]:
    d_from = _parse_iso_date(investment_date_from)
    d_to = _parse_iso_date(investment_date_to)
    ft = (fund_type or "").strip().lower()
    loc = (location or "").strip().lower()
    part_q = (participant_search or "").strip().lower()
    aq = (agent_query or "").strip()

    out: list[dict] = []
    for inv in investments:
        iid = str(inv.get("investmentId") or "").strip()
        pid = str(inv.get("participantId") or "").strip()
        if not iid or not pid:
            continue

        if d_from or d_to:
            idt = _coerce_dt(inv.get("investmentDate")).date()
            if d_from and idt < d_from:
                continue
            if d_to and idt > d_to:
                continue

        if ft:
            fn = str(inv.get("fundName") or "").strip().lower()
            if fn != ft:
                continue

        if loc:
            addr = str((part_by_id.get(pid) or {}).get("address") or "").strip().lower()
            if loc != addr and loc not in addr:
                continue

        if part_q:
            name = str((part_by_id.get(pid) or {}).get("name") or "").lower()
            if part_q not in name and part_q not in iid.lower():
                continue

        if aq and not _investment_matches_agent_query(inv, pc_by_inv.get(iid, []), par_by_id, aq):
            continue

        out.append(inv)
    return out


def _is_assured(inv: dict) -> bool:
    if inv.get("isProfitCapitalPerMonth"):
        return True
    return "assured" in str(inv.get("fundName") or "").lower()


def _expected_total_return(inv: dict, assured: bool) -> float:
    cap = _f(inv.get("investedAmount"))
    monthly = _f(inv.get("monthlyPayout"))
    dur = int(inv.get("durationMonths") or 0)
    if assured:
        return round(monthly * dur, 2)
    return round(cap + monthly * dur, 2)


def _chunks(xs: list, n: int):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _select_all_paged(table: str, *, select_cols: str = "*") -> list[dict]:
    out: list[dict] = []
    start = 0
    while True:
        end = start + _PAGE - 1
        res = (
            supabase.table(table)
            .select(select_cols)
            .range(start, end)
            .execute()
        )
        rows = list(res.data or [])
        out.extend(rows)
        if len(rows) < _PAGE:
            break
        start += _PAGE
    return out


def _select_in_all_paged(
    table: str,
    in_col: str,
    in_values: list[str],
    *,
    select_cols: str = "*",
) -> list[dict]:
    if not in_values:
        return []
    out: list[dict] = []
    start = 0
    while True:
        end = start + _PAGE - 1
        res = (
            supabase.table(table)
            .select(select_cols)
            .in_(in_col, in_values)
            .range(start, end)
            .execute()
        )
        rows = list(res.data or [])
        out.extend(rows)
        if len(rows) < _PAGE:
            break
        start += _PAGE
    return out


def _bank_export(uid: str, bank_by_uid: dict[str, dict]) -> dict[str, str]:
    r = bank_by_uid.get(str(uid).strip()) or {}
    return {
        "bankName": str(r.get("bankName") or ""),
        "accountNumber": str(r.get("accountNumber") or ""),
        "ifscCode": str(r.get("ifscCode") or ""),
    }


def _participant_tds(payout_amount: float, assured: bool, tds_rate: float) -> tuple[float, float]:
    profit_portion = payout_amount / 2.0 if assured else payout_amount
    tds = round(profit_portion * tds_rate, 2)
    net = round(payout_amount - tds, 2)
    return tds, net


def _commission_tds(amount: float, tds_rate: float) -> tuple[float, float]:
    tds = round(amount * tds_rate, 2)
    net = round(amount - tds, 2)
    return tds, net


def _sorted_payment_lines(lines: list[dict]) -> list[dict]:
    return sorted(lines, key=lambda x: int(x.get("monthNumber") or 0))


def _commission_nodes_for_investment(lines: list[dict]) -> dict[str, list[dict]]:
    by_ben: dict[str, list[dict]] = defaultdict(list)
    for row in lines:
        bid = str(row.get("beneficiaryPartnerId") or "").strip()
        if bid:
            by_ben[bid].append(row)
    for bid in by_ben:
        by_ben[bid] = _sorted_payment_lines(by_ben[bid])
    return dict(by_ben)


def _node_aggregates(lines: list[dict]) -> dict[str, Any]:
    amounts = [_f(x.get("amount")) for x in lines]
    n = len(lines)
    total_life = round(sum(amounts), 2)
    avg_mo = round(sum(amounts) / n, 2) if n else 0.0
    m1 = amounts[0] if amounts else 0.0
    m_last = amounts[-1] if amounts else 0.0
    mid = amounts[1] if n > 2 else (amounts[0] if amounts else 0.0)
    return {
        "monthlyBase": round(mid if n > 2 else avg_mo, 2),
        "monthlyAvg": round(avg_mo, 2),
        "firstMonth": round(m1, 2),
        "lastMonth": round(m_last, 2),
        "totalLifetime": total_life,
        "ratePercent": _f(lines[0].get("ratePercent")) if lines else 0.0,
        "level": int(lines[0].get("level") or 0) if lines else 0,
    }


def _empty_export_payload(
    y: int,
    m: int,
    statuses: list[str],
    tds_rate: float,
) -> dict[str, Any]:
    return {
        "closingYear": y,
        "closingMonth": m,
        "investmentStatuses": statuses,
        "tdsRatePercent": round(tds_rate * 100.0, 4),
        "fullHierarchy": [],
        "byInvestment": [],
        "byPartner": [],
        "monthlyParticipants": [],
        "monthlyParticipantSummary": [],
        "monthlyAgentCommissions": [],
        "monthlyAgentSummary": [],
    }


def _partner_role(level: int) -> str:
    if level <= 0:
        return "Direct agent"
    return f"Upline L{level}"


def build_closing_investments_export(
    *,
    year: int,
    month: int,
    investment_statuses: Optional[list[str]] = None,
    tds_rate: float = 0.10,
    partner_name_contains: Optional[str] = None,
    agent_search: Optional[str] = None,
    investment_date_from: Optional[str] = None,
    investment_date_to: Optional[str] = None,
    fund_type: Optional[str] = None,
    location: Optional[str] = None,
    participant_search: Optional[str] = None,
) -> dict[str, Any]:
    """Build all export row lists for ``year``/``month`` (UTC calendar month)."""
    if not (1 <= int(month) <= 12):
        raise ValueError("month must be 1–12")
    y, mo = int(year), int(month)

    for label, s in (
        ("investmentDateFrom", investment_date_from),
        ("investmentDateTo", investment_date_to),
    ):
        if s and str(s).strip() and _parse_iso_date(s) is None:
            raise ValueError(f"{label} must be YYYY-MM-DD")

    statuses = investment_statuses or ["Active"]
    if not statuses:
        statuses = ["Active"]

    agent_query = (agent_search or partner_name_contains or "").strip()

    try:
        all_inv = _select_all_paged(_INV, select_cols="*")
    except APIError as e:
        raise ValueError(str(e)) from e
    statuses_l = {str(s).strip().lower() for s in statuses}
    investments: list[dict] = [
        r for r in all_inv if str(r.get("status") or "").strip().lower() in statuses_l
    ]
    inv_ids = [str(r.get("investmentId") or "").strip() for r in investments if r.get("investmentId")]
    if not inv_ids:
        return _empty_export_payload(y, mo, statuses, tds_rate)

    ps_by_inv: dict[str, list[dict]] = defaultdict(list)
    pc_by_inv: dict[str, list[dict]] = defaultdict(list)

    for chunk in _chunks(inv_ids, 80):
        try:
            ps_rows = _select_in_all_paged(_PS, "investmentId", chunk, select_cols="*")
            for row in ps_rows:
                iid = str(row.get("investmentId") or "").strip()
                if iid:
                    ps_by_inv[iid].append(row)
        except APIError as e:
            raise ValueError(f"payment_schedules: {e}") from e
        try:
            pc_rows = _select_in_all_paged(_PC, "investmentId", chunk, select_cols="*")
            for row in pc_rows:
                iid = str(row.get("investmentId") or "").strip()
                if iid:
                    pc_by_inv[iid].append(row)
        except APIError as e:
            raise ValueError(f"partner_commission_schedules: {e}") from e

    p_pk = camel_participant_pk_column()
    a_pk = camel_partner_pk_column()

    part_ids = sorted({str(r.get("participantId") or "").strip() for r in investments})
    part_ids = [x for x in part_ids if x]
    par_ids: set[str] = set()
    for r in investments:
        ag = str(r.get("agentId") or "").strip()
        if ag:
            par_ids.add(ag)
    for rows in pc_by_inv.values():
        for row in rows:
            bid = str(row.get("beneficiaryPartnerId") or "").strip()
            if bid:
                par_ids.add(bid)
    par_list = sorted(par_ids)

    part_by_id: dict[str, dict] = {}
    par_by_id: dict[str, dict] = {}
    bank_by_uid: dict[str, dict] = {}

    for chunk in _chunks(part_ids, 80):
        try:
            pr = supabase.table("participants").select(f"{p_pk},name,phone,email,address").in_(p_pk, chunk).execute()
            for row in pr.data or []:
                part_by_id[str(row.get(p_pk) or "")] = row
        except APIError:
            pass

    for chunk in _chunks(par_list, 80):
        try:
            ar = supabase.table("partners").select(f"{a_pk},name,phone,email").in_(a_pk, chunk).execute()
            for row in ar.data or []:
                par_by_id[str(row.get(a_pk) or "")] = row
        except APIError:
            pass

    all_uids = sorted(set(part_ids) | set(par_list))
    for chunk in _chunks(all_uids, 80):
        try:
            br = supabase.table(_BANK).select("*").in_("userId", chunk).execute()
            for row in br.data or []:
                bank_by_uid[str(row.get("userId") or "").strip()] = row
        except APIError:
            pass

    investments = _apply_closing_investment_filters(
        investments,
        pc_by_inv=pc_by_inv,
        part_by_id=part_by_id,
        par_by_id=par_by_id,
        investment_date_from=investment_date_from,
        investment_date_to=investment_date_to,
        fund_type=fund_type,
        location=location,
        participant_search=participant_search,
        agent_query=agent_query or None,
    )
    inv_ids = [str(r.get("investmentId") or "").strip() for r in investments if r.get("investmentId")]
    if not investments:
        return _empty_export_payload(y, mo, statuses, tds_rate)

    def inv_core(inv: dict, pid: str) -> dict[str, Any]:
        assured = _is_assured(inv)
        cap = _f(inv.get("investedAmount"))
        monthly = _f(inv.get("monthlyPayout"))
        dur = int(inv.get("durationMonths") or 0)
        roi = _f(inv.get("roiPercentage"))
        iid = str(inv.get("investmentId") or "").strip()
        ps_lines = _sorted_payment_lines(ps_by_inv.get(iid, []))
        paid = sum(1 for ln in ps_lines if str(ln.get("status") or "").lower() == "paid")
        rem = max(0, dur - paid)
        exp_ret = _expected_total_return(inv, assured)
        profit = round(exp_ret - cap, 2)
        st = str(inv.get("status") or "")
        active = st.lower() == "active"
        net_pay = round(rem * monthly, 2) if assured and active else (
            round(cap + rem * monthly, 2) if active else 0.0
        )
        m1 = _f(ps_lines[0].get("amount")) if ps_lines else monthly
        mL = _f(ps_lines[-1].get("amount")) if ps_lines else monthly
        part = part_by_id.get(pid) or {}
        p_bank = _bank_export(pid, bank_by_uid)
        inv_date = _coerce_dt(inv.get("investmentDate")).date().isoformat()
        return {
            "investmentId": iid,
            "participantId": pid,
            "participantName": str(part.get("name") or ""),
            "participantPhone": str(part.get("phone") or ""),
            "location": str(part.get("address") or ""),
            "fundName": str(inv.get("fundName") or ""),
            "isAssuredFund": assured,
            "status": st,
            "investmentDate": inv_date,
            "capital": round(cap, 2),
            "totalProfit": profit,
            "expectedTotalReturn": exp_ret,
            "netPayableRemaining": net_pay,
            "roiPercent": round(roi, 4),
            "durationMonths": dur,
            "paidMonths": paid,
            "remainingMonths": rem,
            "monthlyPayout": round(monthly, 2),
            "firstMonthPayout": round(m1, 2),
            "finalMonthPayout": round(mL, 2),
            "participantBankName": p_bank["bankName"],
            "participantAccountNumber": p_bank["accountNumber"],
            "participantIfsc": p_bank["ifscCode"],
        }

    def partner_cols(bid: str, agg: dict[str, Any]) -> dict[str, Any]:
        par = par_by_id.get(bid) or {}
        b = _bank_export(bid, bank_by_uid)
        lv = int(agg.get("level") or 0)
        return {
            "partnerId": bid,
            "partnerName": str(par.get("name") or ""),
            "partnerPhone": str(par.get("phone") or ""),
            "partnerRole": _partner_role(lv),
            "partnerLevel": lv,
            "partnerCommissionRatePercent": round(_f(agg.get("ratePercent")), 4),
            "partnerMonthlyCommission": agg.get("monthlyBase", 0.0),
            "partnerFirstMonthCommission": agg.get("firstMonth", 0.0),
            "partnerLastMonthCommission": agg.get("lastMonth", 0.0),
            "partnerLifetimeCommission": agg.get("totalLifetime", 0.0),
            "partnerBankName": b["bankName"],
            "partnerAccountNumber": b["accountNumber"],
            "partnerIfsc": b["ifscCode"],
        }

    total_monthly_comm_by_inv: dict[str, float] = {}
    total_lifetime_comm_by_inv: dict[str, float] = {}

    full_hierarchy: list[dict[str, Any]] = []
    by_investment: list[dict[str, Any]] = []
    by_partner: list[dict[str, Any]] = []
    monthly_participants: list[dict[str, Any]] = []

    for inv in investments:
        iid = str(inv.get("investmentId") or "").strip()
        pid = str(inv.get("participantId") or "").strip()
        if not iid or not pid:
            continue
        core = inv_core(inv, pid)
        nodes = _commission_nodes_for_investment(pc_by_inv.get(iid, []))
        tmc = 0.0
        tlc = 0.0
        ordered_bids = sorted(nodes.keys(), key=lambda b: (nodes[b][0].get("level") or 0, b))
        for bid in ordered_bids:
            agg = _node_aggregates(nodes[bid])
            tmc += _f(agg.get("monthlyBase"))
            tlc += _f(agg.get("totalLifetime"))
        total_monthly_comm_by_inv[iid] = round(tmc, 2)
        total_lifetime_comm_by_inv[iid] = round(tlc, 2)

        if not ordered_bids:
            row = {
                **core,
                **{k: None for k in (
                    "partnerId", "partnerName", "partnerPhone", "partnerRole", "partnerLevel",
                    "partnerCommissionRatePercent", "partnerMonthlyCommission",
                    "partnerFirstMonthCommission", "partnerLastMonthCommission",
                    "partnerLifetimeCommission", "partnerBankName", "partnerAccountNumber",
                    "partnerIfsc",
                )},
                "totalMonthlyCommissionAllPartners": total_monthly_comm_by_inv[iid],
                "totalLifetimeCommissionAllPartners": total_lifetime_comm_by_inv[iid],
            }
            full_hierarchy.append(row)
        else:
            for bid in ordered_bids:
                agg = _node_aggregates(nodes[bid])
                if agent_query and not _partner_id_matches_agent_query(bid, par_by_id, agent_query):
                    continue
                full_hierarchy.append({
                    **core,
                    **partner_cols(bid, {**agg, "ratePercent": nodes[bid][0].get("ratePercent")}),
                    "totalMonthlyCommissionAllPartners": total_monthly_comm_by_inv[iid],
                    "totalLifetimeCommissionAllPartners": total_lifetime_comm_by_inv[iid],
                })
                by_partner.append({
                    **partner_cols(bid, {**agg, "ratePercent": nodes[bid][0].get("ratePercent")}),
                    **core,
                    "totalMonthlyCommissionAllPartners": total_monthly_comm_by_inv[iid],
                    "totalLifetimeCommissionAllPartners": total_lifetime_comm_by_inv[iid],
                })

        bi = {
            **core,
            "totalMonthlyCommissionAllPartners": total_monthly_comm_by_inv[iid],
            "totalLifetimeCommissionAllPartners": total_lifetime_comm_by_inv[iid],
        }
        by_investment.append(bi)

        # Monthly participants sheet: all participant schedule lines in month (paid / due / pending)
        ps_lines = ps_by_inv.get(iid, [])
        month_lines_ps = _schedule_lines_in_utc_month(ps_lines, y, mo)
        if not month_lines_ps:
            continue
        payout_amt, payout_date, payout_status = _rollup_participant_month_amount_status(
            month_lines_ps
        )

        if not ordered_bids:
            monthly_participants.append({
                **core,
                "payoutThisMonth": round(payout_amt, 2),
                "payoutDate": payout_date,
                "payoutStatus": payout_status,
                "partnerCommThisMonth": 0.0,
                **{k: None for k in (
                    "partnerId", "partnerName", "partnerPhone", "partnerRole", "partnerLevel",
                    "partnerCommissionRatePercent", "partnerMonthlyCommission",
                    "partnerFirstMonthCommission", "partnerLastMonthCommission",
                    "partnerLifetimeCommission", "partnerBankName", "partnerAccountNumber",
                    "partnerIfsc",
                )},
            })
        else:
            for bid in ordered_bids:
                if agent_query and not _partner_id_matches_agent_query(bid, par_by_id, agent_query):
                    continue
                lines_b = nodes[bid]
                agg = _node_aggregates(lines_b)
                comm_this = 0.0
                for ln in lines_b:
                    if _payout_in_utc_month(ln.get("payoutDate"), y, mo):
                        comm_this += _f(ln.get("amount"))
                comm_this = round(comm_this, 2)
                monthly_participants.append({
                    **core,
                    **partner_cols(bid, {**agg, "ratePercent": lines_b[0].get("ratePercent")}),
                    "payoutThisMonth": round(payout_amt, 2),
                    "payoutDate": payout_date,
                    "payoutStatus": payout_status,
                    "partnerCommThisMonth": round(comm_this, 2),
                })

    by_partner.sort(
        key=lambda r: (
            str(r.get("partnerName") or "").lower(),
            -_coerce_dt(r.get("investmentDate")).timestamp(),
        ),
    )

    # --- monthly participant summary (TDS) — one aggregate row per participant; amounts per investment, not per partner row
    part_sum: dict[str, dict[str, Any]] = {}
    for inv in investments:
        iid = str(inv.get("investmentId") or "").strip()
        pid = str(inv.get("participantId") or "").strip()
        if not iid or not pid:
            continue
        ps_lines = ps_by_inv.get(iid, [])
        month_lines_ps = _schedule_lines_in_utc_month(ps_lines, y, mo)
        if not month_lines_ps:
            continue
        core = inv_core(inv, pid)
        payout, _, _ = _rollup_participant_month_amount_status(month_lines_ps)
        assured = core["isAssuredFund"]
        tds, net_a = _participant_tds(payout, assured, tds_rate)
        agg = part_sum.setdefault(
            pid,
            {
                "participantId": pid,
                "participantName": core["participantName"],
                "investmentCount": 0,
                "totalCapital": 0.0,
                "totalProfit": 0.0,
                "totalNetPayableRemaining": 0.0,
                "totalMonthlyPayout": 0.0,
                "roiSum": 0.0,
                "payoutThisMonthSum": 0.0,
                "tdsDeductedSum": 0.0,
                "netPayableAfterTdsSum": 0.0,
                "investmentIds": [],
            },
        )
        agg["investmentCount"] += 1
        agg["totalCapital"] += _f(core.get("capital"))
        agg["totalProfit"] += _f(core.get("totalProfit"))
        agg["totalNetPayableRemaining"] += _f(core.get("netPayableRemaining"))
        agg["totalMonthlyPayout"] += _f(core.get("monthlyPayout"))
        agg["roiSum"] += _f(core.get("roiPercent"))
        agg["payoutThisMonthSum"] += payout
        agg["tdsDeductedSum"] += tds
        agg["netPayableAfterTdsSum"] += net_a
        agg["investmentIds"].append(iid)

    monthly_participant_summary: list[dict[str, Any]] = []
    for pid, agg in sorted(part_sum.items(), key=lambda x: -x[1]["totalCapital"]):
        n = max(1, int(agg["investmentCount"]))
        avg_roi = round(_f(agg["roiSum"]) / n, 2)
        p_bank = _bank_export(pid, bank_by_uid)
        monthly_participant_summary.append({
            "participantId": agg["participantId"],
            "participantName": agg["participantName"],
            "investmentCount": agg["investmentCount"],
            "totalCapital": round(_f(agg["totalCapital"]), 2),
            "totalProfit": round(_f(agg["totalProfit"]), 2),
            "totalNetPayableRemaining": round(_f(agg["totalNetPayableRemaining"]), 2),
            "totalMonthlyPayout": round(_f(agg["totalMonthlyPayout"]), 2),
            "avgRoiPercent": avg_roi,
            "payoutThisMonth": round(_f(agg["payoutThisMonthSum"]), 2),
            "tdsDeducted": round(_f(agg["tdsDeductedSum"]), 2),
            "netPayableAfterTds": round(_f(agg["netPayableAfterTdsSum"]), 2),
            "investmentIds": ",".join(agg["investmentIds"]),
            "participantBankName": p_bank["bankName"],
            "participantAccountNumber": p_bank["accountNumber"],
            "participantIfsc": p_bank["ifscCode"],
        })

    # --- monthly agent commission lines
    monthly_agent_commissions: list[dict[str, Any]] = []
    for inv in investments:
        iid = str(inv.get("investmentId") or "").strip()
        pid = str(inv.get("participantId") or "").strip()
        if not iid:
            continue
        core = inv_core(inv, pid)
        for ln in pc_by_inv.get(iid, []):
            if not _payout_in_utc_month(ln.get("payoutDate"), y, mo):
                continue
            bid = str(ln.get("beneficiaryPartnerId") or "").strip()
            lines_b = _commission_nodes_for_investment(pc_by_inv.get(iid, [])).get(bid, [])
            agg = _node_aggregates(lines_b) if lines_b else {}
            monthly_agent_commissions.append({
                **{k: core[k] for k in (
                    "investmentId", "participantId", "participantName", "investmentDate",
                    "capital", "fundName", "status",
                )},
                **partner_cols(bid, {**agg, "ratePercent": ln.get("ratePercent")}),
                "commissionMonthNumber": int(ln.get("monthNumber") or 0),
                "commissionPayoutDate": _coerce_dt(ln.get("payoutDate")).date().isoformat(),
                "commissionAmount": round(_f(ln.get("amount")), 2),
                "commissionStatus": str(ln.get("status") or ""),
            })

    # --- monthly agent summary (per Flutter: pair count + node totals + line-level TDS in month)
    agent_sum: dict[str, dict[str, Any]] = {}
    for inv in investments:
        iid = str(inv.get("investmentId") or "").strip()
        pid = str(inv.get("participantId") or "").strip()
        if not iid:
            continue
        nodes = _commission_nodes_for_investment(pc_by_inv.get(iid, []))
        for bid, lines_b in nodes.items():
            if not bid:
                continue
            agg = _node_aggregates(lines_b)
            lv = int(agg.get("level") or 0)
            a = agent_sum.setdefault(
                bid,
                {
                    "partnerId": bid,
                    "partnerName": str((par_by_id.get(bid) or {}).get("name") or ""),
                    "partnerPhone": str((par_by_id.get(bid) or {}).get("phone") or ""),
                    "partnerRole": _partner_role(lv),
                    "investmentCount": 0,
                    "totalMonthlyCommission": 0.0,
                    "totalLifetimeCommission": 0.0,
                    "commDueThisMonth": 0.0,
                    "tdsDeducted": 0.0,
                    "netPayableAfterTds": 0.0,
                    "linesPaid": 0,
                    "linesDue": 0,
                    "linesPending": 0,
                    "investmentIds": [],
                },
            )
            a["investmentCount"] += 1
            a["totalMonthlyCommission"] += _f(agg.get("monthlyBase"))
            a["totalLifetimeCommission"] += _f(agg.get("totalLifetime"))
            if iid not in (a["investmentIds"]):
                a["investmentIds"].append(iid)
            for ln in lines_b:
                if not _payout_in_utc_month(ln.get("payoutDate"), y, mo):
                    continue
                amt = _f(ln.get("amount"))
                a["commDueThisMonth"] += amt
                td, nt = _commission_tds(amt, tds_rate)
                a["tdsDeducted"] += td
                a["netPayableAfterTds"] += nt
                st = str(ln.get("status") or "").lower()
                if st == "paid":
                    a["linesPaid"] += 1
                elif st == "due":
                    a["linesDue"] += 1
                else:
                    a["linesPending"] += 1

    monthly_agent_summary: list[dict[str, Any]] = []
    for bid, a in sorted(
        agent_sum.items(), key=lambda x: -_f(x[1].get("totalLifetimeCommission"))
    ):
        lines_b = []
        for iid0 in inv_ids:
            nodes0 = _commission_nodes_for_investment(pc_by_inv.get(iid0, []))
            if bid in nodes0:
                lines_b = nodes0[bid]
                break
        role = _partner_role(int(lines_b[0].get("level") or 0)) if lines_b else str(a.get("partnerRole") or "")
        bnk = _bank_export(bid, bank_by_uid)
        monthly_agent_summary.append({
            "partnerId": a["partnerId"],
            "partnerName": a["partnerName"],
            "partnerPhone": a["partnerPhone"],
            "partnerRole": role,
            "investmentPartnerPairCount": a["investmentCount"],
            "totalMonthlyCommission": round(_f(a.get("totalMonthlyCommission")), 2),
            "totalLifetimeCommission": round(_f(a.get("totalLifetimeCommission")), 2),
            "commDueThisMonth": round(_f(a.get("commDueThisMonth")), 2),
            "tdsDeducted": round(_f(a.get("tdsDeducted")), 2),
            "netPayableAfterTds": round(_f(a.get("netPayableAfterTds")), 2),
            "linesPaidThisMonth": a.get("linesPaid", 0),
            "linesDueThisMonth": a.get("linesDue", 0),
            "linesPendingThisMonth": a.get("linesPending", 0),
            "investmentIds": ",".join(a.get("investmentIds") or []),
            "partnerBankName": bnk["bankName"],
            "partnerAccountNumber": bnk["accountNumber"],
            "partnerIfsc": bnk["ifscCode"],
        })

    monthly_agent_summary = [
        r
        for r in monthly_agent_summary
        if _f(r.get("commDueThisMonth")) > 0
        or int(r.get("linesPaidThisMonth") or 0)
        + int(r.get("linesDueThisMonth") or 0)
        + int(r.get("linesPendingThisMonth") or 0)
        > 0
    ]

    investment_participant_ids = {
        str(r.get("participantId") or "").strip() for r in investments if r.get("participantId")
    }
    investment_partner_ids = {
        str(r.get("agentId") or "").strip() for r in investments if r.get("agentId")
    }
    for rows in pc_by_inv.values():
        for row in rows:
            bid = str(row.get("beneficiaryPartnerId") or "").strip()
            if bid:
                investment_partner_ids.add(bid)

    try:
        all_participants = _select_all_paged(
            "participants", select_cols=f"{p_pk},name,phone,email,address"
        )
    except APIError:
        all_participants = []
    for row in all_participants:
        pid = str(row.get(p_pk) or "").strip()
        if not pid or pid in investment_participant_ids:
            continue
        name_l = str(row.get("name") or "").lower()
        if participant_search and participant_search.strip().lower() not in name_l:
            continue
        addr_l = str(row.get("address") or "").lower()
        if location:
            qloc = location.strip().lower()
            if qloc != addr_l and qloc not in addr_l:
                continue
        pb = _bank_export(pid, bank_by_uid)
        by_investment.append(
            {
                "investmentId": "",
                "participantId": pid,
                "participantName": str(row.get("name") or ""),
                "participantPhone": str(row.get("phone") or ""),
                "location": str(row.get("address") or ""),
                "fundName": "",
                "isAssuredFund": False,
                "status": "NoInvestment",
                "investmentDate": "",
                "capital": 0.0,
                "totalProfit": 0.0,
                "expectedTotalReturn": 0.0,
                "netPayableRemaining": 0.0,
                "roiPercent": 0.0,
                "durationMonths": 0,
                "paidMonths": 0,
                "remainingMonths": 0,
                "monthlyPayout": 0.0,
                "firstMonthPayout": 0.0,
                "finalMonthPayout": 0.0,
                "participantBankName": pb["bankName"],
                "participantAccountNumber": pb["accountNumber"],
                "participantIfsc": pb["ifscCode"],
                "totalMonthlyCommissionAllPartners": 0.0,
                "totalLifetimeCommissionAllPartners": 0.0,
            }
        )

    try:
        all_partners = _select_all_paged("partners", select_cols=f"{a_pk},name,phone,email")
    except APIError:
        all_partners = []
    for row in all_partners:
        pid = str(row.get(a_pk) or "").strip()
        if not pid or pid in investment_partner_ids:
            continue
        if agent_query and not _partner_id_matches_agent_query(pid, {pid: row}, agent_query):
            continue
        pb = _bank_export(pid, bank_by_uid)
        by_partner.append(
            {
                "partnerId": pid,
                "partnerName": str(row.get("name") or ""),
                "partnerPhone": str(row.get("phone") or ""),
                "partnerRole": "NoInvestment",
                "partnerLevel": 0,
                "partnerCommissionRatePercent": 0.0,
                "partnerMonthlyCommission": 0.0,
                "partnerFirstMonthCommission": 0.0,
                "partnerLastMonthCommission": 0.0,
                "partnerLifetimeCommission": 0.0,
                "partnerBankName": pb["bankName"],
                "partnerAccountNumber": pb["accountNumber"],
                "partnerIfsc": pb["ifscCode"],
                "investmentId": "",
                "participantId": "",
                "participantName": "",
                "participantPhone": "",
                "location": "",
                "fundName": "",
                "isAssuredFund": False,
                "status": "NoInvestment",
                "investmentDate": "",
                "capital": 0.0,
                "totalProfit": 0.0,
                "expectedTotalReturn": 0.0,
                "netPayableRemaining": 0.0,
                "roiPercent": 0.0,
                "durationMonths": 0,
                "paidMonths": 0,
                "remainingMonths": 0,
                "monthlyPayout": 0.0,
                "firstMonthPayout": 0.0,
                "finalMonthPayout": 0.0,
                "totalMonthlyCommissionAllPartners": 0.0,
                "totalLifetimeCommissionAllPartners": 0.0,
            }
        )

    return {
        "closingYear": y,
        "closingMonth": mo,
        "investmentStatuses": statuses,
        "tdsRatePercent": round(tds_rate * 100.0, 4),
        "fullHierarchy": full_hierarchy,
        "byInvestment": by_investment,
        "byPartner": by_partner,
        "monthlyParticipants": monthly_participants,
        "monthlyParticipantSummary": monthly_participant_summary,
        "monthlyAgentCommissions": monthly_agent_commissions,
        "monthlyAgentSummary": monthly_agent_summary,
    }
