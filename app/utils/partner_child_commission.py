"""Direct child self / introducer commission split (parent cap)."""


def child_commission_fields_or_error(parent_self: float, new_child_self: float) -> dict:
    """
    Return ``{ selfCommission, introducerCommission }`` for the child row, or raise ``ValueError``
    with a message suitable for HTTP 400 if the child self exceeds the parent's cap.
    """
    if new_child_self > parent_self + 1e-9:
        raise ValueError(
            f"Child selfCommission cannot exceed parent's selfCommission ({parent_self})",
        )
    intro = max(0.0, round(parent_self - new_child_self, 4))
    return {
        "selfCommission": new_child_self,
        "introducerCommission": intro,
    }
