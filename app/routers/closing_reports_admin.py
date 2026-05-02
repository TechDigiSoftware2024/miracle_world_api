from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.auth import require_role
from app.schemas.closing_reports_admin import (
    ClosingInvestmentsExportResponse,
    ClosingPayoutReportResponse,
)
from app.services.closing_investments_export import build_closing_investments_export
from app.services.closing_reports_query import build_closing_payout_report


router = APIRouter(prefix="/closing-reports", tags=["Admin", "Closing reports"])


@router.get("/payouts", response_model=ClosingPayoutReportResponse)
def admin_closing_payout_report(
    payout_date: Optional[str] = Query(
        None,
        description="Single calendar day YYYY-MM-DD (UTC) on payoutDate",
        alias="payoutDate",
    ),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    payout_date_from: Optional[str] = Query(None, alias="payoutDateFrom"),
    payout_date_to: Optional[str] = Query(None, alias="payoutDateTo"),
    recipient_type: str = Query(
        "all",
        description="all | participant | partner",
        alias="recipientType",
    ),
    user_id: Optional[str] = Query(
        None,
        description="Exact payout userId (participantId or partnerId)",
        alias="userId",
    ),
    name: Optional[str] = Query(
        None,
        description="Case-insensitive participant or partner name contains",
    ),
    payout_status: str = Query(
        "paid",
        description="paid (default for closings) or e.g. pending — empty string for all",
        alias="payoutStatus",
    ),
    _: dict = Depends(require_role(["admin"])),
):
    """
    Export-oriented payout listing: filter by day, month, or date range; enrich with names, phones, and bank_details.
    Requires at least one date scope: ``payoutDate``, or ``year``+``month``, or ``payoutDateFrom``/``payoutDateTo`` (one or both).
    """
    st = (payout_status or "").strip()
    try:
        return build_closing_payout_report(
            payout_date=payout_date,
            year=year,
            month=month,
            payout_date_from=payout_date_from,
            payout_date_to=payout_date_to,
            recipient_type=recipient_type,
            user_id=user_id,
            name_query=name,
            payout_status=st if st else "",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/investments-export", response_model=ClosingInvestmentsExportResponse)
def admin_closing_investments_export(
    year: int = Query(..., ge=2000, le=2100, description="Closing calendar year (UTC)"),
    month: int = Query(..., ge=1, le=12, description="Closing calendar month (UTC)"),
    investment_status: str = Query(
        "Active,Matured,Completed",
        description=(
            "Comma-separated investment row statuses. Default includes matured/completed "
            "so historical closings still show paid months. Use Active only to narrow."
        ),
        alias="investmentStatus",
    ),
    tds_rate_percent: float = Query(
        10.0,
        ge=0.0,
        le=100.0,
        description="TDS as percent (e.g. 10 = 10%% on profit portion / commission)",
        alias="tdsRatePercent",
    ),
    partner_name: str = Query(
        "",
        description="Alias for agentSearch (partner name, id, or phone); prefer agentSearch",
        alias="partnerName",
    ),
    agent_search: str = Query(
        "",
        description="Partner filter: substring on name or id, or phone digits (matches Flutter closing filter)",
        alias="agentSearch",
    ),
    investment_date_from: Optional[str] = Query(
        None,
        description="Investment date lower bound YYYY-MM-DD (UTC date of investmentDate)",
        alias="investmentDateFrom",
    ),
    investment_date_to: Optional[str] = Query(
        None,
        description="Investment date upper bound YYYY-MM-DD (inclusive)",
        alias="investmentDateTo",
    ),
    fund_type: Optional[str] = Query(
        None,
        description="Exact fund name chip (case-insensitive) — same as investments.fundName",
        alias="fundType",
    ),
    location: Optional[str] = Query(
        None,
        description="Participant address filter: exact (case-insensitive) or substring, like location chip",
        alias="location",
    ),
    participant_search: str = Query(
        "",
        description="Substring on participant name or investment id (app bar search)",
        alias="participantSearch",
    ),
    _: dict = Depends(require_role(["admin"])),
):
    """
    Investment-centric closing data for Excel export: mirrors typical 4-sheet monthly closing
    (participants, participant summary with TDS, agent commission lines, agent summary with TDS)
    plus full hierarchy, by-investment, and by-partner row sets. Schedule rows match the month via
    ``payoutDate`` (UTC wall calendar).

    **Filters** align with the admin Closing screen: status list, partner search (name / id / phone),
    investment date range, fund type chip, location (participant address), and participant search.

    **Closing month**: ``year`` + ``month`` select the UTC calendar month for participant and partner
    schedule rows. Rows are included for **paid, due, and pending** line status — this endpoint is for
    export/reconciliation, not only outstanding accruals.
    """
    statuses = [s.strip() for s in (investment_status or "").split(",") if s.strip()]
    tds_rate = tds_rate_percent / 100.0
    try:
        raw = build_closing_investments_export(
            year=year,
            month=month,
            investment_statuses=statuses,
            tds_rate=tds_rate,
            partner_name_contains=partner_name.strip() or None,
            agent_search=agent_search.strip() or None,
            investment_date_from=investment_date_from,
            investment_date_to=investment_date_to,
            fund_type=fund_type.strip() if fund_type and fund_type.strip() else None,
            location=location.strip() if location and location.strip() else None,
            participant_search=participant_search.strip() or None,
        )
        return ClosingInvestmentsExportResponse.model_validate(raw)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
