from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.investment import (
    AdminInvestmentFundStatsItem,
    AdminInvestmentStatsResponse,
    InvestmentAdminCreate,
    InvestmentAdminUpdate,
    InvestmentResponse,
    InvestmentStatusUpdate,
    PartnerCommissionScheduleResponse,
    PaymentScheduleResponse,
)
from app.utils.investment_id import new_investment_id
from app.utils.db_column_names import camel_participant_pk_column, camel_partner_pk_column
from app.services.investment_actions import replace_payment_schedules
from app.services.partner_commission_schedule import (
    delete_partner_commission_schedules,
    replace_partner_commission_schedules,
)
from app.services.partner_portfolio_recalc import (
    recalculate_all_partner_portfolios,
    recalculate_partner_portfolio,
)
from app.services.participant_portfolio_recalc import (
    recalculate_all_participant_portfolios,
    recalculate_participant_portfolio,
    recalc_from_investment_id,
)
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/investments", tags=["Admin", "Investments"])


def _require_super_admin(current_user: dict) -> None:
    if str(current_user.get("adminRole") or "").strip().lower() != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin may run this operation",
        )


class ResetInvestmentPipelineRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    truncate_tables: bool = Field(
        True,
        validation_alias=AliasChoices("truncateTables", "truncate_tables"),
        description="If true, call PostgreSQL function reset_investment_tables() (apply supabase_reset_investment_pipeline.sql first).",
    )


class ResetInvestmentPipelineResponse(BaseModel):
    truncated: bool
    partners_recalculated: int
    participants_recalculated: int

_TABLE = "investments"
_PS = "payment_schedules"
_PC = "partner_commission_schedules"


def _row_inv_or_404(investment_id: str) -> dict:
    result = supabase.table(_TABLE).select("*").eq("investmentId", investment_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investment not found",
        )
    return result.data[0]


@router.get("", response_model=List[InvestmentResponse])
def admin_list_investments(
    participant_id: Optional[str] = Query(None, description="Filter by participant id"),
    _: dict = Depends(require_role(["admin"])),
):
    try:
        q = supabase.table(_TABLE).select("*").order("createdAt", desc=True)
        if participant_id is not None and str(participant_id).strip():
            q = q.eq("participantId", str(participant_id).strip())
        result = q.execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [InvestmentResponse.model_validate(r) for r in (result.data or [])]


def _parse_fund_id_key(raw) -> tuple[str, Optional[int]]:
    """Group key and optional numeric fund type id."""
    if raw is None:
        return ("", None)
    s = str(raw).strip()
    if not s:
        return ("", None)
    try:
        return (s, int(s))
    except (TypeError, ValueError):
        return (s, None)


def _row_count(
    table: str,
    pk: str,
    *,
    status_value: Optional[str] = None,
) -> int:
    try:
        q = supabase.table(table).select(pk, count="exact")
        if status_value is not None:
            q = q.eq("status", status_value)
        r = q.limit(0).execute()
        return int(r.count or 0)
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


def _empty_fund_bucket(num_id: Optional[int], gk: str) -> dict:
    return {
        "numId": num_id,
        "key": gk,
        "amount": 0.0,
        "n": 0,
        "participants": set(),
        "partners": set(),
    }


@router.get("/stats", response_model=AdminInvestmentStatsResponse)
def admin_investment_stats(
    fund_type_id: list[int] = Query(
        default=[],
        description=(
            "If set, only these `fund_types.id` are listed in **funds** (still includes zero-activity). "
            "Omit to list all fund types."
        ),
    ),
    _: dict = Depends(require_role(["admin"])),
):
    """
    **Admin dashboard** numbers: app-wide user counts, pending join requests, portfolio totals, then per–fund-type activity.
    """
    p_pk = camel_participant_pk_column()
    a_pk = camel_partner_pk_column()

    n_participants = _row_count("participants", p_pk)
    n_partners = _row_count("partners", a_pk)
    n_pending = _row_count("user_requests", "id", status_value="pending")

    _FT = "fund_types"
    try:
        ft_res = (
            supabase.table(_FT)
            .select("id, fundName")
            .order("id")
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    ft_rows: list[dict] = list(ft_res.data or [])

    try:
        inv_res = supabase.table(_TABLE).select(
            "fundId, investedAmount, participantId, agentId"
        ).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    rows = inv_res.data or []

    total_amt = 0.0
    for r in rows:
        try:
            total_amt += float(r.get("investedAmount") or 0)
        except (TypeError, ValueError):
            pass
    total_n = len(rows)

    by_key: dict[str, dict] = {}
    for r in rows:
        raw_fid = r.get("fundId")
        gk, num_id = _parse_fund_id_key(raw_fid)
        if gk not in by_key:
            by_key[gk] = _empty_fund_bucket(num_id, gk)
        b = by_key[gk]
        b["numId"] = num_id if b.get("numId") is None else b["numId"]
        try:
            b["amount"] += float(r.get("investedAmount") or 0)
        except (TypeError, ValueError):
            pass
        b["n"] += 1
        pid = r.get("participantId")
        ag = r.get("agentId")
        if pid is not None and str(pid).strip():
            b["participants"].add(str(pid).strip())
        if ag is not None and str(ag).strip():
            b["partners"].add(str(ag).strip())

    allow_ids: Optional[set[int]] = None
    if fund_type_id:
        allow_ids = set(fund_type_id)

    def _row_from_bucket(
        fund_id: Optional[int], name: str, b: dict
    ) -> AdminInvestmentFundStatsItem:
        return AdminInvestmentFundStatsItem(
            fundId=fund_id,
            fundName=name,
            totalInvestedAmount=round(b["amount"], 2),
            investmentCount=b["n"],
            userInvestorCount=len(b["participants"]),
            partnerCount=len(b["partners"]),
        )

    fund_items: list[AdminInvestmentFundStatsItem] = []
    for ft in ft_rows:
        fid = int(ft["id"])
        if allow_ids is not None and fid not in allow_ids:
            continue
        gk = str(fid)
        label = str(ft.get("fundName") or ft.get("fund_name") or "").strip() or f"Fund {fid}"
        b = by_key.get(gk) or _empty_fund_bucket(fid, gk)
        fund_items.append(_row_from_bucket(fid, label, b))

    known_numeric = {str(int(ft["id"])) for ft in ft_rows}
    if allow_ids is None and "" in by_key and by_key[""]["n"] > 0:
        fund_items.append(
            _row_from_bucket(
                None,
                "Unspecified",
                by_key[""],
            )
        )
    if allow_ids is None:
        for gk, b in sorted(by_key.items(), key=lambda it: it[0] or ""):
            if gk in known_numeric or gk == "":
                continue
            if b["n"] == 0:
                continue
            label = f"Other ({gk})" if gk else "Unspecified"
            fund_items.append(
                _row_from_bucket(
                    b.get("numId"),
                    label,
                    b,
                )
            )

    return AdminInvestmentStatsResponse(
        totalInvestedAmount=round(total_amt, 2),
        totalInvestmentCount=total_n,
        totalParticipantsInApp=n_participants,
        totalPartnersInApp=n_partners,
        pendingUserRequestsCount=n_pending,
        funds=fund_items,
    )


@router.get("/pending", response_model=List[InvestmentResponse])
def admin_list_pending_investments(
    _: dict = Depends(require_role(["admin"])),
):
    """
    All investments not yet **Active**: **Processing** and **Pending Approval** (pre-activation workflow).
    Newest first.
    """
    try:
        result = (
            supabase.table(_TABLE)
            .select("*")
            .in_("status", ["Processing", "Pending Approval"])
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [InvestmentResponse.model_validate(r) for r in (result.data or [])]


@router.post("/reset-pipeline", response_model=ResetInvestmentPipelineResponse)
def admin_reset_investment_pipeline(
    body: ResetInvestmentPipelineRequest = ResetInvestmentPipelineRequest(),
    current_user: dict = Depends(require_role(["admin"])),
):
    """
    Truncate all investment + schedule data (optional) and recompute every partner
    (introducer commission amount, team size, business totals, schedule-based amounts)
    and participant portfolio fields. **super_admin** only.
    """
    _require_super_admin(current_user)
    truncated = False
    if body.truncate_tables:
        try:
            supabase.rpc("reset_investment_tables", {}).execute()
            truncated = True
        except APIError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{format_api_error(e)} "
                    "If the function is missing, run supabase_reset_investment_pipeline.sql in the Supabase SQL editor, "
                    "or call this endpoint with truncateTables false after truncating manually."
                ),
            ) from e
    p_count = recalculate_all_participant_portfolios()
    k_count = recalculate_all_partner_portfolios()
    return ResetInvestmentPipelineResponse(
        truncated=truncated,
        participants_recalculated=p_count,
        partners_recalculated=k_count,
    )


@router.post("", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED)
def admin_create_investment(
    payload: InvestmentAdminCreate,
    _: dict = Depends(require_role(["admin"])),
):
    iid = new_investment_id()
    inv_date = payload.investmentDate or datetime.now(timezone.utc)
    body = {
        "investmentId": iid,
        "participantId": payload.participantId.strip(),
        "agentId": payload.agentId,
        "fundId": payload.fundId,
        "fundName": payload.fundName,
        "investedAmount": float(payload.investedAmount),
        "roiPercentage": float(payload.roiPercentage),
        "durationMonths": int(payload.durationMonths),
        "investmentDate": inv_date.isoformat() if isinstance(inv_date, datetime) else inv_date,
        "nextPayoutDate": None,
        "monthlyPayout": float(payload.monthlyPayout or 0),
        "isProfitCapitalPerMonth": payload.isProfitCapitalPerMonth,
        "status": payload.status,
        "investmentStartDate": None,
        "investmentDoc": "",
        "updatedAt": None,
    }
    try:
        inserted = supabase.table(_TABLE).insert(body).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    row = inserted.data[0] if inserted.data else None
    if not row:
        refetch = supabase.table(_TABLE).select("*").eq("investmentId", iid).execute()
        row = refetch.data[0] if refetch.data else None
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read investment after insert.",
        )
    part = str(payload.participantId).strip()
    recalculate_participant_portfolio(part)
    ag = str(payload.agentId or "").strip()
    if ag:
        recalculate_partner_portfolio(ag)
    return InvestmentResponse.model_validate(row)


@router.get("/{investment_id}/payment-schedules", response_model=List[PaymentScheduleResponse])
def admin_list_payment_schedules(
    investment_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    _row_inv_or_404(investment_id)
    try:
        result = (
            supabase.table(_PS)
            .select("*")
            .eq("investmentId", investment_id)
            .order("monthNumber")
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [PaymentScheduleResponse.model_validate(r) for r in (result.data or [])]


@router.get(
    "/{investment_id}/partner-commission-schedules",
    response_model=List[PartnerCommissionScheduleResponse],
)
def admin_list_partner_commission_schedules(
    investment_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    """Monthly commission accrual lines (all beneficiaries) for this investment."""
    _row_inv_or_404(investment_id)
    try:
        result = (
            supabase.table(_PC)
            .select("*")
            .eq("investmentId", investment_id)
            .order("monthNumber")
            .order("level")
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [
        PartnerCommissionScheduleResponse.model_validate(r) for r in (result.data or [])
    ]


@router.get("/{investment_id}", response_model=InvestmentResponse)
def admin_get_investment(
    investment_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    return InvestmentResponse.model_validate(_row_inv_or_404(investment_id))


@router.patch("/{investment_id}", response_model=InvestmentResponse)
def admin_patch_investment(
    investment_id: str,
    payload: InvestmentAdminUpdate,
    _: dict = Depends(require_role(["admin"])),
):
    before = _row_inv_or_404(investment_id)
    old_agent = str(before.get("agentId") or "").strip()
    data = dump_update_or_400(payload)
    flat = {}
    for k, v in data.items():
        if v is None:
            continue
        if isinstance(v, datetime):
            flat[k] = v.isoformat()
        elif k in ("investedAmount", "roiPercentage", "monthlyPayout"):
            flat[k] = float(v)
        elif k == "durationMonths":
            flat[k] = int(v)
        else:
            flat[k] = v
    now = datetime.now(timezone.utc).isoformat()
    flat["updatedAt"] = now
    try:
        updated = (
            supabase.table(_TABLE)
            .update(flat)
            .eq("investmentId", investment_id)
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table(_TABLE).select("*").eq("investmentId", investment_id).execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read investment after update.",
            )
        recalc_from_investment_id(investment_id)
        new_agent = str(row.get("agentId") or "").strip()
        if old_agent and old_agent != new_agent:
            recalculate_partner_portfolio(old_agent)
        return InvestmentResponse.model_validate(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.patch("/{investment_id}/status", response_model=InvestmentResponse)
def admin_patch_investment_status(
    investment_id: str,
    payload: InvestmentStatusUpdate,
    _: dict = Depends(require_role(["admin"])),
):
    row = _row_inv_or_404(investment_id)
    old_status = row.get("status")
    new_status = payload.status
    now = datetime.now(timezone.utc).isoformat()

    start = payload.investmentStartDate
    if new_status == "Active":
        if start is None:
            start = datetime.now(timezone.utc)
        elif start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        patch = {
            "status": new_status,
            "investmentStartDate": start.isoformat(),
            "updatedAt": now,
        }
        merged = dict(row)
        merged["monthlyPayout"] = float(merged.get("monthlyPayout") or 0)
        merged["durationMonths"] = int(merged.get("durationMonths") or 0)
        try:
            next_iso = replace_payment_schedules(investment_id, merged, start)
            patch["nextPayoutDate"] = next_iso
            replace_partner_commission_schedules(investment_id, merged, start)
        except APIError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=format_api_error(e),
            ) from e
    else:
        patch = {"status": new_status, "updatedAt": now}
        if (
            str(old_status or "").strip() == "Active"
            and str(new_status or "").strip() in ("Processing", "Pending Approval")
        ):
            try:
                supabase.table(_PS).delete().eq("investmentId", investment_id).execute()
                delete_partner_commission_schedules(investment_id)
            except APIError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=format_api_error(e),
                ) from e
            patch["nextPayoutDate"] = None

    try:
        updated = (
            supabase.table(_TABLE)
            .update(patch)
            .eq("investmentId", investment_id)
            .execute()
        )
        out = updated.data[0] if updated.data else None
        if not out:
            refetch = (
                supabase.table(_TABLE).select("*").eq("investmentId", investment_id).execute()
            )
            out = refetch.data[0] if refetch.data else None
        if not out:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not read investment after update.",
            )
        recalc_from_investment_id(investment_id)
        return InvestmentResponse.model_validate(out)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.delete("/{investment_id}")
def admin_delete_investment(
    investment_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    inv = _row_inv_or_404(investment_id)
    part_id = str(inv.get("participantId") or "").strip()
    agent_id = str(inv.get("agentId") or "").strip()
    try:
        supabase.table(_TABLE).delete().eq("investmentId", investment_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if part_id:
        recalculate_participant_portfolio(part_id)
    if agent_id:
        recalculate_partner_portfolio(agent_id)
    return {"message": "Investment deleted", "investmentId": investment_id}
