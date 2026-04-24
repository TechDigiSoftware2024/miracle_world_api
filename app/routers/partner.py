from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from postgrest.exceptions import APIError

from app.db.database import supabase
from app.dependencies.auth import bearer_scheme, require_role
from app.core.security import create_token, decode_token
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.investment import InvestmentResponse
from app.schemas.partner import (
    PartnerAccountBasicResponse,
    PartnerResponse,
    PartnerSelfProfilePatch,
    PartnerTeamMemberNode,
    SetChildSelfCommissionRequest,
)
from app.schemas.reward_program import (
    RewardOfferResponse,
    RewardProgramResponse,
    RewardProgramWithOffersResponse,
)
from app.services.partner_portfolio_recalc import recalculate_partner_portfolio
from app.utils.db_column_names import camel_partner_pk_column
from app.utils.partner_team import team_tree_for_partner
from app.utils.patch_payload import dump_update_or_400
from app.utils.supabase_errors import format_api_error

router = APIRouter(prefix="/partner", tags=["Partner"])

_TABLE_INV = "investments"


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
    result = (
        supabase.table("partners")
        .select("*")
        .eq("phone", sub)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found",
        )
    return result.data[0]


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
    response_model=PartnerAccountBasicResponse,
    summary="Same as GET /partner/account (basic details only)",
)
def get_partner_profile(
    current_user: dict = Depends(require_role(["partner"])),
):
    return _row_to_account_basic(_partner_row_by_phone(current_user["sub"]))


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


# ─── Downline team tree (children only; no parent nodes) ───────


@router.get(
    "/team",
    response_model=PartnerTeamMemberNode,
    summary="Downline partner tree rooted at logged-in partner",
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
    summary="Parent sets direct child partner selfCommission; child introducerCommission = parent.self − child.self",
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
    p_self = float(parent_row.get("selfCommission") or 0)
    new_child_self = float(payload.selfCommission)
    if new_child_self > p_self + 1e-9:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Child selfCommission cannot exceed parent's selfCommission ({p_self})",
        )
    intro_comm = max(0.0, round(p_self - new_child_self, 4))
    try:
        supabase.table("partners").update({
            "selfCommission": new_child_self,
            "introducerCommission": intro_comm,
        }).eq(pk, child_id).execute()
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
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
    _: dict = Depends(require_role(["partner"])),
):
    """Partner-only. Returns **`isActive` = true** programs, each with its **offers** (newest programs first)."""
    try:
        prog = (
            supabase.table("reward_programs")
            .select("*")
            .eq("isActive", True)
            .order("startDate", desc=True)
            .execute()
        )
        rows = prog.data or []
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
        by_pid: dict[int, list] = {}
        for o in off.data or []:
            pid = int(o.get("programId"))
            by_pid.setdefault(pid, []).append(o)
        out: list[RewardProgramWithOffersResponse] = []
        for r in rows:
            pid = int(r["id"])
            offers = [RewardOfferResponse.model_validate(x) for x in by_pid.get(pid, [])]
            base = RewardProgramResponse.model_validate(r)
            out.append(
                RewardProgramWithOffersResponse.model_validate({
                    **base.model_dump(),
                    "offers": [o.model_dump() for o in offers],
                })
            )
        return out
    except APIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=format_api_error(e),
        ) from e
