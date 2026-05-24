from pydantic import BaseModel
from typing import Optional


class StripeWebhookEvent(BaseModel):
    type: str
    data: dict


class StripeCheckoutSession(BaseModel):
    session_id: str
    client_email: str
    client_name: str
    package: str
    amount: float
