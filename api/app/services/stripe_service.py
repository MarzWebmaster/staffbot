"""
Stripe payment integration service.

Handles:
- Creating Stripe Checkout sessions
- Processing webhook events
- Verifying payment intents
"""
import stripe
from fastapi import HTTPException, status
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
