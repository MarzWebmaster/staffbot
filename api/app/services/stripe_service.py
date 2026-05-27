"""
Stripe payment integration service.

Handles:
- Creating Stripe Checkout sessions
- Processing webhook events
- Verifying payment intents
"""
import stripe
from fastapi import HTTPException, status
from datetime import datetime, timezone
from app.config import get_settings

settings = get_settings()

# Only configure Stripe if API key is set
if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeService:
    @staticmethod
    def is_configured() -> bool:
        return bool(settings.STRIPE_SECRET_KEY)

    @staticmethod
    async def create_checkout_session(
        name: str,
        email: str,
        package: str,
        amount: float,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        """Create a Stripe Checkout Session."""
        if not StripeService.is_configured():
            return {
                "id": f"cs_test_{package}_{email}",
                "url": f"{settings.LANDING_PAGE_URL}/checkout/simulate?package={package}&email={email}",
                "test_mode": True,
            }

        try:
            session = stripe.checkout.Session.create(
                customer_email=email,
                payment_method_types=["card", "fpx"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "myr",
                            "product_data": {
                                "name": f"StaffBot.my - {package.title()}",
                            },
                            "unit_amount": int(amount * 100),  # cents
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "package": package,
                    "customer_name": name,
                    "customer_email": email,
                },
            )
            return {"id": session.id, "url": session.url, "test_mode": False}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Stripe checkout error: {str(e)}",
            )

    @staticmethod
    async def verify_webhook(payload: bytes, sig_header: str) -> dict:
        """Verify and parse Stripe webhook event.

        ALWAYS verifies signature. No test-mode bypass.
        """
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Stripe webhook not configured",
            )

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
            return event
        except stripe.error.SignatureVerificationError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook signature",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Webhook error: {str(e)}",
            )

    @staticmethod
    async def get_account_info() -> dict:
        """Get Stripe account info (connection status)."""
        if not StripeService.is_configured():
            return {"connected": False, "detail": "Stripe API key not set"}

        try:
            account = stripe.Account.retrieve()
            return {
                "connected": True,
                "account_name": account.get("business_profile", {}).get("name", account.get("id", "")),
                "livemode": account.get("livemode", False),
                "country": account.get("country", ""),
                "email": account.get("email", ""),
            }
        except Exception as e:
            return {"connected": False, "detail": str(e)}

    @staticmethod
    async def get_recent_transactions(limit: int = 10) -> list:
        """Get recent payment intents."""
        if not StripeService.is_configured():
            return []

        try:
            payments = stripe.PaymentIntent.list(limit=limit)
            items = []
            for p in payments.data:
                items.append({
                    "id": p.id,
                    "amount": p.amount / 100,
                    "currency": p.currency.upper(),
                    "status": p.status,
                    "client_name": p.metadata.get("customer_name", ""),
                    "client_email": p.metadata.get("customer_email", ""),
                    "package": p.metadata.get("package", ""),
                    "created_at": datetime.fromtimestamp(p.created, tz=timezone.utc).isoformat(),
                })
            return items
        except Exception:
            return []
