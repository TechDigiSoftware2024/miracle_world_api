"""Keep child partners' introducerCommission aligned with parent.selfCommission − child.selfCommission."""

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.services.partner_portfolio_recalc import recalculate_partner_portfolio
from app.utils.db_column_names import camel_partner_pk_column


def sync_children_introducer_commission_rates(parent_partner_id: str) -> None:
    """Recompute introducerCommission for every direct child partner of this parent."""
    pid = str(parent_partner_id or "").strip()
    if not pid:
        return
    pk = camel_partner_pk_column()
    try:
        pr = supabase.table("partners").select("*").eq(pk, pid).limit(1).execute()
    except APIError:
        return
    if not pr.data:
        return
    p_self = float(pr.data[0].get("selfCommission") or 0)
    try:
        ch = supabase.table("partners").select("*").eq("introducer", pid).execute()
    except APIError:
        return
    for row in ch.data or []:
        cid = str(row.get(pk) or row.get("agentId") or "").strip()
        if not cid:
            continue
        c_self = float(row.get("selfCommission") or 0)
        ic = max(0.0, round(p_self - c_self, 4))
        try:
            supabase.table("partners").update({"introducerCommission": ic}).eq(pk, cid).execute()
        except APIError:
            continue
        recalculate_partner_portfolio(cid)
