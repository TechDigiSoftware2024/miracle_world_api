"""Background sync after admin mark-paid (participant schedules)."""

from __future__ import annotations

import logging
from collections import defaultdict

from app.services.investment_actions import sync_investment_status_with_payment_lines
from app.services.partner_commission_schedule import sync_partner_commission_status_for_month
from app.services.participant_portfolio_recalc import recalc_from_investment_ids

logger = logging.getLogger(__name__)


def run_participant_mark_paid_post_process(inv_to_months: dict[str, list[int]]) -> None:
    """
    Partner commission sync, investment status sync, and portfolio recalc for investments
    whose participant payment schedule lines were marked paid in this request.
    """
    if not inv_to_months:
        return
    months_by_inv: dict[str, set[int]] = defaultdict(set)
    for iid, months in inv_to_months.items():
        iid = str(iid or "").strip()
        if not iid:
            continue
        for mn in months:
            try:
                months_by_inv[iid].add(int(mn))
            except (TypeError, ValueError):
                continue
    affected = sorted(months_by_inv.keys())
    for iid in affected:
        for mn in sorted(months_by_inv[iid]):
            try:
                sync_partner_commission_status_for_month(iid, mn, "paid")
            except Exception as e:
                logger.warning(
                    "mark_paid post-process: partner commission sync failed %s m%s: %s",
                    iid,
                    mn,
                    e,
                )
        try:
            sync_investment_status_with_payment_lines(iid)
        except Exception as e:
            logger.warning(
                "mark_paid post-process: investment sync failed %s: %s", iid, e
            )
    try:
        recalc_from_investment_ids(affected)
    except Exception as e:
        logger.warning("mark_paid post-process: portfolio recalc failed: %s", e)
