"""Stripe payment integration service — with top-up support."""

import stripe
from typing import Optional
from fastapi import HTTPException, status

# Module-level state — configured dynamically from DB at runtime
_stripe_secret_key: str = ""
_stripe_webhook_secret: str = ""


class StripeService:
    """Stripe payment integration.

    Keys are loaded dynamically from DB settings by each caller router.
    After calling configure(), all subsequent Stripe calls use those keys.
    """

    @staticmethod
    def configure(secret_key: str, webhook_secret: str = "") -> None:
        """Configure Stripe with keys loaded from DB settings."""
        global _stripe_secret_key, _stripe_webhook_secret
        _stripe_secret_key = secret_key
        _stripe_webhook_secret = webhook_secret
        if secret_key:
            stripe.api_key = secret_key

    @staticmethod
    def is_configured() -> bool:
        return bool(_stripe_secret_key)

    @staticmethod
    async def configure_from_db(db) -> None:
        """Load Stripe keys from DB settings table and configure Stripe."""
        from sqlalchemy import select
        from app.models.setting import Setting
        from app.utils.encryption import decrypt_value
        try:
            result = await db.execute(
                select(Setting).where(
                    Setting.key.in_(["stripe_secret_key", "stripe_webhook_secret"])
                )
            )
            settings_map = {}
            for s in result.scalars().all():
                val = decrypt_value(s.value) if s.encrypted else s.value
                if s.key == "stripe_secret_key":
                    settings_map["secret_key"] = val
                elif s.key == "stripe_webhook_secret":
                    settings_map["webhook_secret"] = val
            StripeService.configure(
                secret_key=settings_map.get("secret_key", ""),
                webhook_secret=settings_map.get("webhook_secret", ""),
            )
        except Exception:
            # Don't crash if settings table doesn't exist yet
            pass

    @staticmethod
    async def create_checkout_session(
        name: str,
        email: str,
        package: str,
        amount: float,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        """Create a Stripe Checkout Session for subscription.

        If Stripe is not configured, returns a simulated checkout URL.
        """
        if not StripeService.is_configured():
            return {
                "id": f"cs_test_{package}_{email}",
                "url": f"https://staffbot.my/payment/simulate",
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
        """Create a Stripe Checkout Session for token top-up.

        If Stripe is not configured, returns a simulated checkout URL.
        """
        if not StripeService.is_configured():
            return {
                "id": f"cs_topup_{client_id}_{package_id}",
                "url": f"https://staffbot.my/billing/topup-simulate",
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
    async def get_account_info() -> dict:
        """Get Stripe account information.

        Returns connected status, account name, and mode (live/test).
        If not configured, returns {"connected": False}.
        """
        if not StripeService.is_configured():
            return {
                "connected": False,
                "detail": "Stripe not configured. Enter your keys in Payment Gateway page.",
            }
        try:
            account = stripe.Account.retrieve()
            return {
                "connected": True,
                "account_name": account.get("business_profile", {}).get("name", account.get("settings", {}).get("dashboard", {}).get("display_name", "Stripe Account")),
                "livemode": account.get("livemode", False),
                "country": account.get("country", ""),
                "email": account.get("email", ""),
            }
        except Exception as e:
            return {
                "connected": False,
                "detail": f"Stripe API error: {str(e)}",
            }

    @staticmethod
    async def get_recent_transactions(limit: int = 10) -> list:
        """Get recent Stripe payment transactions."""
        if not StripeService.is_configured():
            return []
        try:
            charges = stripe.Charge.list(limit=limit)
            transactions = []
            for charge in charges:
                metadata = charge.get("metadata", {})
                transactions.append({
                    "id": charge.get("id"),
                    "amount": charge.get("amount", 0) / 100.0,
                    "currency": charge.get("currency", "myr").upper(),
                    "status": charge.get("status", "unknown"),
                    "customer_email": charge.get("billing_details", {}).get("email", charge.get("receipt_email", "")),
                    "description": charge.get("description", ""),
                    "metadata": {
                        "type": metadata.get("type", ""),
                        "package": metadata.get("package", ""),
                        "customer_name": metadata.get("customer_name", ""),
                    },
                    "created_at": charge.get("created"),
                    "receipt_url": charge.get("receipt_url", ""),
                })
            return transactions
        except Exception:
            return []

    @staticmethod
    async def verify_webhook(payload: bytes, sig_header: str) -> dict:
        """Verify and parse Stripe webhook event.

        Uses the webhook secret configured via configure().
        """
        if not _stripe_webhook_secret:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Stripe webhook not configured",
            )
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, _stripe_webhook_secret
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
