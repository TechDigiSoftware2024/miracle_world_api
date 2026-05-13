from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.investment import InvestmentResponse, PartnerCommissionScheduleResponse
from app.schemas.partner import (
    PartnerAccountBasicResponse,
    PartnerProfileResponse,
    PartnerResponse,
    PartnerSelfProfilePatch,
    PartnerTeamMemberNode,
    SetChildSelfCommissionRequest,
)
from app.schemas.reward_program import (
    PartnerRewardProgramCard,
    PartnerRewardProgramsResponse,
    PartnerRewardProgramsSummary,
    RewardOfferResponse,
    RewardProgramProgress,
    RewardProgramResponse,
    RewardProgramWithOffersResponse,
)
from app.services.partner_portfolio_recalc import recalculate_partner_portfolio
from app.services.reward_achievement_compute import compute_progress_for_partner_program
from app.services.reward_achievement_compute import (
    fetch_partner_achievement_rows,
    goal_amount_rupees,
    list_active_non_expired_programs,
    qualifying_amount,
    recompute_partner_reward_achievements,
)
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.phone_normalize import normalize_phone_digits
from app.utils.partner_child_commission import child_commission_fields_or_error
from app.utils.partner_commission import sync_children_introducer_commission_rates
from app.utils.partner_team import team_tree_for_partner
from app.utils.patch_payload import dump_update_or_400
from app.utils.file_uploads import save_upload_file
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/partner", tags=["Partner"])

_TABLE_INV = "investments"
_TABLE_PC = "partner_commission_schedules"


def _list_active_reward_program_rows() -> list[dict]:
    """
    Read active reward programs with compatibility for camelCase/snake_case DB columns.
    """
    try:
        res = (
            supabase.table("reward_programs")
            .select("*")
            .eq("isActive", True)
            .order("startDate", desc=True)
            .execute()
        )
        return res.data or []
    except APIError as first_err:
        msg = str(first_err).lower()
        # Some environments still use snake_case columns.
        if "column" not in msg and "isactive" not in msg:
            raise
    res = (
        supabase.table("reward_programs")
        .select("*")
        .eq("is_active", True)
        .order("startDate", desc=True)
        .execute()
    )
    return res.data or []


def _program_sort_key(row: dict) -> tuple[str, str, float, int]:
    return (
        str(row.get("programType") or "").upper(),
        str(row.get("businessType") or "ALL").upper() or "ALL",
        float(row.get("goalAmountValue") or 0),
        int(row.get("id") or 0),
    )


def _program_track_key(row: dict) -> tuple[str, str]:
    return (
        str(row.get("programType") or "").upper(),
        str(row.get("businessType") or "ALL").upper() or "ALL",
    )


def _row_to_account_basic(row: dict) -> PartnerAccountBasicResponse:
    return PartnerAccountBasicResponse(
        partnerId=str(row.get("partnerId") or row.get("agentId") or ""),
        name=str(row.get("name") or ""),
        phone=str(row.get("phone") or ""),
        email=str(row.get("email") or ""),
        location=str(row.get("location") or ""),
        profileImage=str(row.get("profileImage") or ""),
        status=str(row.get("status") or ""),
        createdAt=row["createdAt"],
    )


def _partner_row_by_phone(sub: str) -> dict:
    """Resolve partner row by JWT ``sub`` (phone). Tries normalized 10-digit India form then raw value."""
    raw = str(sub or "").strip()
    candidates: list[str] = []
    d10 = normalize_phone_digits(raw)
    if d10 and len(d10) == 10:
        candidates.append(d10)
    if raw and raw not in candidates:
        candidates.append(raw)
    for phone in candidates:
        result = (
            supabase.table("partners")
            .select("*")
            .eq("phone", phone)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Partner not found",
    )


def _partner_row_for_profile(current_user: dict) -> dict:
    """
    Row used for GET /partner/profile.

    - ``partner`` role: lookup by phone (``sub``).
    - ``participant`` role: if the same phone has a partner account, use that row (unified login
      returns participant first; app can open partner profile without forcing swap-role first).
    """
    role = str(current_user.get("role") or "").strip().lower()
    sub = str(current_user.get("sub") or "").strip()
    if role == "partner":
        return _partner_row_by_phone(sub)
    if role == "participant":
        d10 = normalize_phone_digits(sub)
        for phone in ([d10] if d10 and len(d10) == 10 else []) + ([sub] if sub else []):
            if not phone:
                continue
            res = (
                supabase.table("partners")
                .select("*")
                .eq("phone", phone)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "No partner account for this phone. Log in with a partner account, "
                "or use POST /swap-role if you have both participant and partner on the same number."
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this resource",
    )


# ─── PUBLIC: Login ───────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
def partner_login(payload: LoginRequest):
    result = (
        supabase.table("partners")
        .select("*")
        .eq("phone", payload.phone)
        .eq("mpin", payload.mpin)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or mpin",
        )

    partner = result.data[0]
    uid = str(partner.get("partnerId") or partner.get("agentId") or "")
    token = create_token({
        "sub": partner["phone"],
        "role": "partner",
        "userId": uid,
        "name": partner["name"],
    })

    return TokenResponse(
        access_token=token,
        role="partner",
        userId=uid,
        name=partner["name"],
    )


# ─── PROTECTED: Logout ──────────────────────────────────────────


@router.post("/logout")
def partner_logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    current_user: dict = Depends(require_role(["partner", "admin"])),
):
    token = credentials.credentials
    payload = decode_token(token)
    jti = payload.get("jti")

    existing = supabase.table("token_blacklist").select("id").eq("jti", jti).execute()
    if not existing.data:
        supabase.table("token_blacklist").insert({"jti": jti}).execute()

    return {"message": "Logged out successfully"}


# ─── PROTECTED: Account (basic) ─────────────────────────────────


@router.get(
    "/account",
    response_model=PartnerAccountBasicResponse,
    summary="Partner account basics (no MPIN or financials)",
)
def get_partner_account(
    current_user: dict = Depends(require_role(["partner"])),
):
    return _row_to_account_basic(_partner_row_by_phone(current_user["sub"]))


@router.get(
    "/profile",
    response_model=PartnerProfileResponse,
    summary=(
        "Full partner row with MLM/portfolio fields (mpin omitted). "
        "Set recalculate=false to return stored aggregates faster and avoid 504s on slow networks; "
        "default recalculate=true refresues portfolio + reward progress from source tables."
    ),
)
def get_partner_profile(
    recalculate: bool = Query(
        True,
        description=(
            "When true (default), recomputes portfolio columns from investments and commission schedules "
            "before returning. When false, returns the current partners row as stored (faster; use for "
            "dashboard refresh if you recalculate elsewhere or accept slightly stale numbers)."
        ),
    ),
    current_user: dict = Depends(require_role(["partner", "participant"])),
):
    base = _partner_row_for_profile(current_user)
    uid = str(
        base.get("partnerId")
        or base.get("agentId")
        or current_user.get("userId")
        or "",
    ).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Partner record is missing partnerId",
        )
    if recalculate:
        recalculate_partner_portfolio(uid)
    prid = camel_partner_pk_column()
    try:
        result = (
            supabase.table("partners")
            .select("*")
            .eq(prid, uid)
            .limit(1)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found",
        )
    return PartnerProfileResponse.model_validate(result.data[0])


@router.patch("/profile", response_model=PartnerAccountBasicResponse)
def patch_partner_profile(
    payload: PartnerSelfProfilePatch,
    current_user: dict = Depends(require_role(["partner"])),
):
    data = dump_update_or_400(payload)
    try:
        updated = (
            supabase.table("partners")
            .update(data)
            .eq("phone", current_user["sub"])
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("partners")
                .select("*")
                .eq("phone", current_user["sub"])
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        uid = str(current_user.get("userId", "")).strip()
        if uid:
            recalculate_partner_portfolio(uid)
            prid = camel_partner_pk_column()
            again = (
                supabase.table("partners")
                .select("*")
                .eq(prid, uid)
                .execute()
            )
            if again.data:
                row = again.data[0]
        return _row_to_account_basic(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.post("/profile-image/upload", response_model=PartnerAccountBasicResponse)
def partner_upload_profile_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role(["partner"])),
):
    stored_path = save_upload_file(file, "profile_images")
    try:
        updated = (
            supabase.table("partners")
            .update({"profileImage": stored_path})
            .eq("phone", current_user["sub"])
            .execute()
        )
        row = updated.data[0] if updated.data else None
        if not row:
            refetch = (
                supabase.table("partners")
                .select("*")
                .eq("phone", current_user["sub"])
                .execute()
            )
            row = refetch.data[0] if refetch.data else None
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner not found",
            )
        return _row_to_account_basic(row)
    except HTTPException:
        raise
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


# ─── Investments linked to this partner (agentId) ──────────────


@router.get(
    "/investments",
    response_model=List[InvestmentResponse],
    summary="Investments where this partner is agent (introducer)",
)
def partner_list_investments(
    current_user: dict = Depends(require_role(["partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    try:
        result = (
            supabase.table(_TABLE_INV)
            .select("*")
            .eq("agentId", uid)
            .order("createdAt", desc=True)
            .execute()
        )
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [InvestmentResponse.model_validate(r) for r in (result.data or [])]


@router.get(
    "/commission-schedules",
    response_model=List[PartnerCommissionScheduleResponse],
    summary="Monthly commission accrual lines where logged-in partner receives payment",
)
def partner_list_commission_schedules(
    investment_id: Optional[str] = Query(
        None,
        description="Filter by investment id.",
    ),
    from_: Optional[datetime] = Query(
        None,
        alias="from",
        description="Inclusive lower bound on payoutDate (UTC).",
    ),
    to: Optional[datetime] = Query(
        None,
        description="Inclusive upper bound on payoutDate (UTC).",
    ),
    current_user: dict = Depends(require_role(["partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    try:
        q = (
            supabase.table(_TABLE_PC)
            .select("*")
            .eq("beneficiaryPartnerId", uid)
        )
        inv_f = str(investment_id or "").strip()
        if inv_f:
            q = q.eq("investmentId", inv_f)
        if from_ is not None:
            ts = from_
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            q = q.gte("payoutDate", ts.isoformat())
        if to is not None:
            ts = to
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            q = q.lte("payoutDate", ts.isoformat())
        result = q.order("payoutDate").order("investmentId").order("level").execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    return [
        PartnerCommissionScheduleResponse.model_validate(r) for r in (result.data or [])
    ]


# ─── Downline team tree (children only; no parent nodes) ───────


@router.get(
    "/team",
    response_model=PartnerTeamMemberNode,
    summary="Downline partner tree rooted at logged-in partner",
    description=(
        "Recursive tree of introducer → children. Each node includes "
        "**selfCommissionLockedByParentApp** when the partner-app one-time child commission save "
        "was already used for that node (as child)."
    ),
)
def partner_get_team_tree(
    current_user: dict = Depends(require_role(["partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is missing userId",
        )
    tree = team_tree_for_partner(uid)
    if tree is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found",
        )
    return tree


@router.post(
    "/team/{child_partner_id}/commission",
    response_model=PartnerResponse,
    summary="Parent sets direct child selfCommission (one-time per child via partner app)",
    description=(
        "Updates the **direct** child's **selfCommission** and **introducerCommission** "
        "(introducer = parent.self − child.self). **Only one successful POST per child** from the "
        "partner app; after that, **409** until an admin uses the admin commission endpoint. "
        "Run **`supabase_partners_self_commission_locked_by_parent_app.sql`** if the lock column is missing."
    ),
)
def partner_set_child_self_commission(
    child_partner_id: str,
    payload: SetChildSelfCommissionRequest,
    current_user: dict = Depends(require_role(["partner"])),
):
    parent_id = str(current_user.get("userId", "")).strip()
    child_id = str(child_partner_id or "").strip()
    if not parent_id or not child_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid partner id",
        )
    if parent_id == child_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot set commission for yourself",
        )
    pk = camel_partner_pk_column()
    try:
        pr = supabase.table("partners").select("*").eq(pk, parent_id).limit(1).execute()
        cr = supabase.table("partners").select("*").eq(pk, child_id).limit(1).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    if not pr.data or not cr.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent or child partner not found",
        )
    parent_row, child_row = pr.data[0], cr.data[0]
    if str(child_row.get("introducer") or "").strip() != parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This partner is not your direct child (introducer mismatch)",
        )
    if bool(child_row.get("selfCommissionLockedByParentApp")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Commission for this direct partner was already set from the partner app. "
                "Contact an administrator to change it."
            ),
        )
    p_self = float(parent_row.get("selfCommission") or 0)
    new_child_self = float(payload.selfCommission)
    try:
        patch = child_commission_fields_or_error(p_self, new_child_self)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    patch["selfCommissionLockedByParentApp"] = True
    try:
        supabase.table("partners").update(patch).eq(pk, child_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
    sync_children_introducer_commission_rates(child_id)
    recalculate_partner_portfolio(child_id)
    refetch = supabase.table("partners").select("*").eq(pk, child_id).limit(1).execute()
    if not refetch.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read child partner after update",
        )
    return PartnerResponse.model_validate(refetch.data[0])


# ─── REWARD PROGRAMS (active programs + offers) ─────────────────


@router.get(
    "/reward-programs",
    response_model=list[RewardProgramWithOffersResponse],
    summary="List active reward programs with offers",
)
def partner_list_active_reward_programs(
    current_user: dict = Depends(require_role(["partner"])),
):
    """Partner-only. Returns **`isActive` = true** programs, each with its **offers** (newest programs first)."""
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing userId",
        )
    try:
        rows = _list_active_reward_program_rows()
        if not rows:
            return []
        ids = [int(r["id"]) for r in rows]
        off = (
            supabase.table("reward_offers")
            .select("*")
            .in_("programId", ids)
            .order("createdAt", desc=True)
            .execute()
        )
        by_prog: dict[int, list] = {}
        for o in off.data or []:
            gid = int(o.get("programId"))
            by_prog.setdefault(gid, []).append(o)
        out: list[RewardProgramWithOffersResponse] = []
        for r in rows:
            prog_id = int(r["id"])
            offers = [RewardOfferResponse.model_validate(x) for x in by_prog.get(prog_id, [])]
            base = RewardProgramResponse.model_validate(r)
            try:
                raw_prog = compute_progress_for_partner_program(r, uid)
            except Exception:
                raw_prog = []
            prog_models = [RewardProgramProgress.model_validate(x) for x in raw_prog]
            has_eligible = any(p.goalReached for p in prog_models)
            out.append(
                RewardProgramWithOffersResponse.model_validate({
                    **base.model_dump(),
                    "offers": [o.model_dump() for o in offers],
                    "progress": [p.model_dump() for p in prog_models],
                    "hasEligibleReward": has_eligible,
                })
            )
        return out
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e


@router.get(
    "/reward-programs/progress",
    response_model=PartnerRewardProgramsResponse,
    summary="Partner reward levels with lock/unlock state and totals",
)
def partner_reward_programs_progress(
    refresh: bool = Query(
        True,
        description="When true, recompute and persist partner achievements before response.",
    ),
    current_user: dict = Depends(require_role(["partner"])),
):
    uid = str(current_user.get("userId", "")).strip()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing userId",
        )

    if refresh:
        try:
            recompute_partner_reward_achievements(uid)
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    programs = list_active_non_expired_programs(now)
    if not programs:
        return PartnerRewardProgramsResponse(
            partnerId=uid,
            generatedAt=now,
            summary=PartnerRewardProgramsSummary(),
            programs=[],
        )

    program_ids = [int(p.get("id") or 0) for p in programs if int(p.get("id") or 0) > 0]
    rows_by_program = fetch_partner_achievement_rows(uid, program_ids)

    try:
        offers_raw = (
            supabase.table("reward_offers")
            .select("*")
            .in_("programId", program_ids)
            .order("createdAt", desc=True)
            .execute()
        ).data or []
    except APIError:
        offers_raw = []
    offers_by_program: dict[int, list[RewardOfferResponse]] = {}
    for o in offers_raw:
        pid = int(o.get("programId") or 0)
        if pid > 0:
            offers_by_program.setdefault(pid, []).append(RewardOfferResponse.model_validate(o))

    grouped: dict[tuple[str, str], list[dict]] = {}
    for p in sorted(programs, key=_program_sort_key):
        grouped.setdefault(_program_track_key(p), []).append(p)

    cards: list[PartnerRewardProgramCard] = []
    for _, plist in grouped.items():
        previous_achieved = True
        for p in plist:
            pid = int(p.get("id") or 0)
            prog_rows = rows_by_program.get(pid, [])
            latest = prog_rows[-1] if prog_rows else None
            latest_direct = float((latest or {}).get("directPaidInPeriod") or 0)
            latest_team = float((latest or {}).get("teamPaidInPeriod") or 0)
            g_rupees = goal_amount_rupees(
                float(p.get("goalAmountValue") or 0),
                str(p.get("goalAmountUnit") or "LAKH"),
            )
            eligible = qualifying_amount(latest_direct, latest_team, p.get("businessType"))
            remaining = max(0.0, round(g_rupees - eligible, 2))
            progress = 0.0 if g_rupees <= 0 else min(100.0, round((eligible / g_rupees) * 100.0, 2))
            achieved_row = next((r for r in prog_rows if bool(r.get("goalReached"))), None)
            is_achieved = achieved_row is not None
            is_current = (not is_achieved) and previous_achieved
            is_locked = not is_achieved and (not previous_achieved)
            previous_achieved = previous_achieved and is_achieved
            end_dt = p.get("endDate")
            is_expired = False
            try:
                is_expired = bool(end_dt) and (datetime.fromisoformat(str(end_dt).replace("Z", "+00:00")) < now)
            except (TypeError, ValueError):
                is_expired = False
            ach_at_raw = (achieved_row or {}).get("achievedAt")
            ach_at = None
            if ach_at_raw is not None:
                try:
                    ach_at = datetime.fromisoformat(str(ach_at_raw).replace("Z", "+00:00"))
                except ValueError:
                    ach_at = None

            cards.append(
                PartnerRewardProgramCard(
                    program=RewardProgramResponse.model_validate(p),
                    offers=offers_by_program.get(pid, []),
                    isAchieved=is_achieved,
                    isCurrent=is_current,
                    isLocked=is_locked,
                    isExpired=is_expired,
                    goalAmountRupees=g_rupees,
                    directAmount=round(latest_direct, 2),
                    teamAmount=round(latest_team, 2),
                    eligibleAmount=round(eligible, 2),
                    remainingAmount=round(remaining, 2),
                    progressPercent=progress,
                    achievedAt=ach_at,
                    latestPeriodKey=str((latest or {}).get("periodKey") or ""),
                    latestPeriodStart=(latest or {}).get("periodStart"),
                    latestPeriodEnd=(latest or {}).get("periodEnd"),
                )
            )

    summary = PartnerRewardProgramsSummary(
        totalPrograms=len(cards),
        achievedPrograms=sum(1 for c in cards if c.isAchieved),
        unlockedPrograms=sum(1 for c in cards if (not c.isLocked)),
        lockedPrograms=sum(1 for c in cards if c.isLocked),
        expiredPrograms=sum(1 for c in cards if c.isExpired),
        totalGoalAmountRupees=round(sum(c.goalAmountRupees for c in cards), 2),
        totalEligibleAmount=round(sum(c.eligibleAmount for c in cards), 2),
        totalDirectAmount=round(sum(c.directAmount for c in cards), 2),
        totalTeamAmount=round(sum(c.teamAmount for c in cards), 2),
        totalRewardAmount=round(sum(c.eligibleAmount for c in cards if c.isAchieved), 2),
    )
    return PartnerRewardProgramsResponse(
        partnerId=uid,
        generatedAt=now,
        summary=summary,
        programs=cards,
    )
