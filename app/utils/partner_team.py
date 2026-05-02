"""Build partner downline trees (introducer → child partners only)."""

from __future__ import annotations

from typing import Optional

from postgrest.exceptions import APIError

from app.db.database import supabase
from app.schemas.partner import PartnerTeamMemberNode
from app.utils.db_column_names import camel_partner_pk_column


def _partner_pk(row: dict, pk_col: str) -> str:
    return str(row.get(pk_col) or row.get("agentId") or row.get("partnerId") or "").strip()


def fetch_all_partner_rows() -> list[dict]:
    try:
        r = supabase.table("partners").select("*").execute()
        return list(r.data or [])
    except APIError:
        return []


def partners_by_introducer(rows: list[dict], pk_col: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        pid = _partner_pk(row, pk_col)
        if not pid:
            continue
        intro = str(row.get("introducer") or "").strip()
        out.setdefault(intro, []).append(row)
    for k in out:
        out[k].sort(key=lambda x: _partner_pk(x, pk_col))
    return out


def _node_from_row(row: dict, pk_col: str, children: list[PartnerTeamMemberNode]) -> PartnerTeamMemberNode:
    pid = _partner_pk(row, pk_col)
    ic = row.get("introducerCommission")
    if ic is None and row.get("commission") is not None:
        ic = row.get("commission")
    return PartnerTeamMemberNode(
        partnerId=pid,
        name=str(row.get("name") or ""),
        phone=str(row.get("phone") or ""),
        email=str(row.get("email") or ""),
        location=str(row.get("location") or ""),
        status=str(row.get("status") or ""),
        selfCommission=float(row.get("selfCommission") or 0),
        introducerCommission=float(ic or 0),
        selfCommissionLockedByParentApp=bool(
            row.get("selfCommissionLockedByParentApp", False)
        ),
        children=children,
    )


def build_subtree(
    root_row: dict,
    by_intro: dict[str, list[dict]],
    pk_col: str,
    visited: Optional[set[str]] = None,
) -> PartnerTeamMemberNode:
    """Recursive downline only (no parent link in payload). Cycle-safe."""
    if visited is None:
        visited = set()
    rid = _partner_pk(root_row, pk_col)
    if not rid:
        return _node_from_row(root_row, pk_col, [])
    if rid in visited:
        return _node_from_row(root_row, pk_col, [])
    visited.add(rid)
    child_rows = by_intro.get(rid, [])
    child_nodes = [build_subtree(cr, by_intro, pk_col, visited) for cr in child_rows]
    return _node_from_row(root_row, pk_col, child_nodes)


def team_tree_for_partner(partner_id: str) -> Optional[PartnerTeamMemberNode]:
    """Full downline tree rooted at `partner_id` (includes root as top node)."""
    pid = str(partner_id or "").strip()
    if not pid:
        return None
    pk_col = camel_partner_pk_column()
    rows = fetch_all_partner_rows()
    root_row: Optional[dict] = None
    for r in rows:
        if _partner_pk(r, pk_col) == pid:
            root_row = r
            break
    if not root_row:
        return None
    by_intro = partners_by_introducer(rows, pk_col)
    return build_subtree(root_row, by_intro, pk_col, set())


def count_downline_partners(partner_id: str) -> int:
    """
    Number of partners in the subtree under ``partner_id`` (direct + indirect children only;
    does not include ``partner_id``). Cycle-safe BFS over ``introducer`` edges.
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return 0
    pk_col = camel_partner_pk_column()
    rows = fetch_all_partner_rows()
    by_intro = partners_by_introducer(rows, pk_col)
    count = 0
    stack = list(by_intro.get(pid, []))
    seen: set[str] = set()
    while stack:
        row = stack.pop()
        cid = _partner_pk(row, pk_col)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        count += 1
        stack.extend(by_intro.get(cid, []))
    return count


def downline_partner_ids_including_self(partner_id: str) -> list[str]:
    """
    ``partner_id`` first, then every descendant partner reachable via ``introducer`` (cycle-safe BFS).
    Used for group business volume (direct + team book).
    """
    pid = str(partner_id or "").strip()
    if not pid:
        return []
    pk_col = camel_partner_pk_column()
    rows = fetch_all_partner_rows()
    by_intro = partners_by_introducer(rows, pk_col)
    out: list[str] = [pid]
    stack = list(by_intro.get(pid, []))
    seen: set[str] = {pid}
    while stack:
        row = stack.pop()
        cid = _partner_pk(row, pk_col)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
        stack.extend(by_intro.get(cid, []))
    return out
