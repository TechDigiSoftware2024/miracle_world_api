from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import require_role
from app.schemas.participant_special_funds import (
    AdminSpecialFundsAssign,
    AdminSpecialFundsMutationResponse,
    AdminSpecialFundsRemove,
    ParticipantSpecialFundIdsResponse,
)
from app.utils.db_column_names import camel_participant_pk_column
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/participants/special-funds", tags=["Admin", "Participants", "Fund types"])

_JUNCTION = "participant_special_funds"
_FT = "fund_types"


def _validate_special_fund_ids(fund_type_ids: list[int]) -> None:
    if not fund_type_ids:
        return
    try:
        res = (
            supabase.table(_FT)
            .select("id,isSpecial,status")
            .in_("id", fund_type_ids)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    rows = res.data or []
    if len(rows) != len(set(fund_type_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more fundTypeIds do not exist",
        )
    for r in rows:
        if not r.get("isSpecial"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fund type {r.get('id')} is not marked as special (isSpecial)",
            )
        if str(r.get("status") or "").lower() != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fund type {r.get('id')} must be active to assign to participants",
            )


def _ensure_participants_exist(participant_ids: list[str]) -> None:
    pid_col = camel_participant_pk_column()
    try:
        res = (
            supabase.table("participants")
            .select(pid_col)
            .in_(pid_col, participant_ids)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    found = {str(r[pid_col]) for r in (res.data or [])}
    missing = [p for p in participant_ids if p not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown participantId(s): {', '.join(missing[:10])}"
            + ("…" if len(missing) > 10 else ""),
        )


@router.post("/assign", response_model=AdminSpecialFundsMutationResponse)
def admin_assign_special_funds(
    payload: AdminSpecialFundsAssign,
    _: dict = Depends(require_role(["admin"])),
):
    raw_pids = [str(x).strip() for x in payload.participantIds]
    if not raw_pids or not all(raw_pids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="participantIds must be non-empty strings",
        )
    pids = list(dict.fromkeys(raw_pids))
    fids = list(dict.fromkeys(int(x) for x in payload.fundTypeIds))
    _ensure_participants_exist(pids)
    _validate_special_fund_ids(fids)

    pid_col = camel_participant_pk_column()
    rows = [{"participantId": pid, "fundTypeId": fid} for pid in pids for fid in fids]
    try:
        if payload.setIsEligible:
            for pid in pids:
                supabase.table("participants").update({"isEligible": True}).eq(pid_col, pid).execute()
        for chunk_start in range(0, len(rows), 100):
            chunk = rows[chunk_start : chunk_start + 100]
            supabase.table(_JUNCTION).upsert(chunk, on_conflict="participantId,fundTypeId").execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    return AdminSpecialFundsMutationResponse(
        participantIds=pids,
        fundTypeIdsAffected=fids,
        linksUpserted=len(rows),
        linksRemoved=0,
    )


@router.post("/remove", response_model=AdminSpecialFundsMutationResponse)
def admin_remove_special_funds(
    payload: AdminSpecialFundsRemove,
    _: dict = Depends(require_role(["admin"])),
):
    raw_pids = [str(x).strip() for x in payload.participantIds]
    if not raw_pids or not all(raw_pids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="participantIds must be non-empty strings",
        )
    pids = list(dict.fromkeys(raw_pids))
    _ensure_participants_exist(pids)

    fid_list = [int(x) for x in payload.fundTypeIds] if payload.fundTypeIds else None
    try:
        for pid in pids:
            q = supabase.table(_JUNCTION).delete().eq("participantId", pid)
            if fid_list:
                q = q.in_("fundTypeId", fid_list)
            q.execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e

    affected_fids = list(dict.fromkeys(int(x) for x in (fid_list or [])))
    return AdminSpecialFundsMutationResponse(
        participantIds=pids,
        fundTypeIdsAffected=affected_fids,
        linksUpserted=0,
        linksRemoved=0,
    )


@router.get("/{participant_id}", response_model=ParticipantSpecialFundIdsResponse)
def admin_get_participant_special_funds(
    participant_id: str,
    _: dict = Depends(require_role(["admin"])),
):
    pid_col = camel_participant_pk_column()
    try:
        pr = (
            supabase.table("participants")
            .select(f'{pid_col},"isEligible"')
            .eq(pid_col, participant_id)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not pr.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        )
    row = pr.data[0]
    elig = bool(row.get("isEligible"))
    try:
        jr = (
            supabase.table(_JUNCTION)
            .select("fundTypeId")
            .eq("participantId", participant_id)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    fund_ids = sorted({int(r["fundTypeId"]) for r in (jr.data or [])})
    return ParticipantSpecialFundIdsResponse(
        participantId=participant_id,
        isEligible=elig,
        eligibleSpecialFundIds=fund_ids,
    )
