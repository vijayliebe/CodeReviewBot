# Controllers must not access the data layer directly (Rule: no-direct-db-in-controllers)
from models import UserPaymentModel

def check_payment_status(request):
    payment_id = request.get("id")
    # Direct data-layer query violates the architectural rule
    status = UserPaymentModel.find_by_id(payment_id)
    return {"status": "success", "data": status}
