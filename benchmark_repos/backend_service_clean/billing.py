"""Clean backend service — should produce ZERO findings (FP control)."""
import logging
from decimal import Decimal
import redis

logger = logging.getLogger(__name__)


def process_billing(user_id, amount):
    charge = Decimal(str(amount)) * Decimal("1.05")
    if charge <= 0:
        raise ValueError("Amount must be positive")

    r = redis.Redis()
    r.set(f"backend:session:{user_id}", "active")
    return charge


def refund(user_id, amount):
    try:
        return Decimal(str(amount)) * Decimal("0.9")
    except ValueError as exc:
        logger.warning("Refund failed: %s", exc)
        return Decimal("0")
