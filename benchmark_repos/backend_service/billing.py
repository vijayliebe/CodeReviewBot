import redis
from decimal import Decimal


def process_billing(user_id, amount):
    # VIOLATION (no-float-for-money): Using float for billing calculations
    charge = float(amount) * 1.05

    r = redis.Redis()
    # VIOLATION (redis-key-prefix): missing 'backend:' prefix
    r.set(f"session:{user_id}", "active")

    # Inline override — should NOT trigger no-float-for-money
    legacy_charge = float(amount)  # crb:ignore no-float-for-money

    # crb:rule "Ensure all database writes check if amount is positive"
    if charge <= 0:
        raise ValueError("Amount must be positive")

    return charge


def refund(user_id, amount):
    # VIOLATION (bare-except): bare except hides errors
    try:
        return Decimal(str(amount)) * Decimal("0.9")
    except:
        return 0
