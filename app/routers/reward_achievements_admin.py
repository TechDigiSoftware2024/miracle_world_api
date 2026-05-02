"""Admin: reward achievers list and full recomputation for a program."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.reward_program import (
    RewardAchievementAdminRow,
    RewardAchievementRecomputeResponse,
)
from app.services.reward_achievement_compute import recompute_program_achievements
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.supabase_errors import format_api_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reward-achievements", tags=["Admin", "Reward achievements"])

_TABLE = "reward_program_achievements"
_PROGRAMS = "reward_programs"


def _row_or_404_program(program_id: int) -> dict:
    r = supabase.table(_PROGRAMS).select("*").eq("id", program_id).limit(1).execute()
    if not r.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reward program not found")
    return r.data[0]


@router.get("", response_model=List[RewardAchievementAdminRow])
def admin_list_reward_achievements(
    program_id: Optional[int] = Query(None, alias="programId"),
    program_type: Optional[str] = Query(
        None,
        description="MONTHLY | ULTIMATE — filter by program type",
        alias="programType",
    ),
    goal_reached_only: bool = Query(False, alias="goalReachedOnly"),
    partner_id: Optional[str] = Query(None, alias="partnerId"),
    _: dict = Depends(require_role(["admin"])),
):
    """
    Achievers / progress rows persisted by **recompute** (see `POST .../recompute`).
    Partner live progress is also on `GET /partner/reward-programs` without waiting for recompute.
    """
    try:
        type_ids: Optional[set[int]] = None
        if program_type and str(program_type).strip().upper() in ("MONTHLY", "ULTIMATE"):
            pt = str(program_type).strip().upper()
            pr = (
                supabase.table(_PROGRAMS)
                .select("id")
                .eq("programType", pt)
                .execute()
            )
            type_ids = {int(x["id"]) for x in (pr.data or [])}

        q = supabase.table(_TABLE).select("*").order("computedAt", desc=True)
        if program_id is not None:
            q = q.eq("programId", int(program_id))
        if goal_reached_only:
            q = q.eq("goalReached", True)
        if partner_id and str(partner_id).strip():
            q = q.eq("partnerId", str(partner_id).strip())
        res = q.execute()
        rows = list(res.data or [])
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    if type_ids is not None:
        rows = [r for r in rows if int(r.get("programId") or 0) in type_ids]

    prog_ids = sorted({int(r.get("programId") or 0) for r in rows if r.get("programId") is not None})
    part_ids = sorted({str(r.get("partnerId") or "").strip() for r in rows if r.get("partnerId")})
    prog_by_id: dict[int, dict] = {}
    if prog_ids:
        try:
            for i in range(0, len(prog_ids), 80):
                chunk = prog_ids[i : i + 80]
                pr = supabase.table(_PROGRAMS).select("id,title,programType").in_("id", chunk).execute()
                for p in pr.data or []:
                    prog_by_id[int(p["id"])] = p
        except APIError:
            pass
    pk = camel_partner_pk_column()
    part_by_id: dict[str, dict] = {}
    if part_ids:
        try:
            for i in range(0, len(part_ids), 80):
                chunk = part_ids[i : i + 80]
                pr = supabase.table("partners").select(f"{pk},name,phone").in_(pk, chunk).execute()
                for p in pr.data or []:
                    part_by_id[str(p.get(pk) or "")] = p
        except APIError:
            pass

    out: list[RewardAchievementAdminRow] = []
    for r in rows:
        pid = int(r.get("programId") or 0)
        pr = prog_by_id.get(pid) or {}
        par_id = str(r.get("partnerId") or "")
        par = part_by_id.get(par_id) or {}
        out.append(
            RewardAchievementAdminRow.model_validate(
                {
                    **r,
                    "partnerName": str(par.get("name") or ""),
                    "partnerPhone": str(par.get("phone") or ""),
                    "programTitle": str(pr.get("title") or ""),
                    "programType": str(pr.get("programType") or ""),
                }
            )
        )
    return out


@router.post(
    "/recompute/{program_id}",
    response_model=RewardAchievementRecomputeResponse,
    summary="Rebuild achievement rows for all partners (after program date/goal edits)",
)
def admin_recompute_reward_achievements(
    program_id: int,
    _: dict = Depends(require_role(["admin"])),
):
    _row_or_404_program(program_id)
    try:
        n = recompute_program_achievements(program_id)
    except Exception as e:
        logger.exception("recompute reward achievements: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    return RewardAchievementRecomputeResponse(programId=program_id, rowsWritten=n)
