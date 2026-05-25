"""Stripe payment integration service — with top-up support."""
import stripe
from fastapi import HTTPException, status
from app.config import get_settings

settings = get_settings()

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
        """Create a Stripe Checkout Session for subscription."""
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
                            "unit_amount": int(amount * 100),
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "type": "subscription",
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
    async def create_topup_session(
        client_id: int,
        name: str,
        email: str,
        package_id: int,
        package_name: str,
        tokens: int,
        amount: float,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        """Create a Stripe Checkout Session for token top-up."""
        if not StripeService.is_configured():
            return {
                "id": f"cs_topup_{client_id}_{package_id}",
                "url": f"{settings.LANDING_PAGE_URL}/billing/topup-simulate?client_id={client_id}&tokens={tokens}",
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
                                "name": f"StaffBot Token Top-Up: {package_name}",
                                "description": f"{tokens:,} tokens",
                            },
                            "unit_amount": int(amount * 100),
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "type": "topup",
                    "client_id": str(client_id),
                    "package_id": str(package_id),
                    "tokens": str(tokens),
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
        """Verify and parse Stripe webhook event."""
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
