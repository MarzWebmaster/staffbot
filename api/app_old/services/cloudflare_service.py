"""
Cloudflare API integration service.

Handles:
- Adding/removing DNS A records for client subdomains
- Listing DNS records
"""
import httpx
from fastapi import HTTPException, status
from app.config import get_settings

settings = get_settings()


class CloudflareService:
    BASE_URL = "https://api.cloudflare.com/client/v4"

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ZONE_ID)

    @staticmethod
    def _headers() -> dict:
        return {
            "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }

    @staticmethod
    async def create_dns_record(
        subdomain: str,
        ip_address: str,
        proxy: bool = False,
    ) -> dict:
        """Create an A record for client subdomain."""
        if not CloudflareService.is_configured():
            return {
                "success": True,
                "test_mode": True,
                "record": {
                    "name": f"{subdomain}.{settings.DOMAIN}",
                    "type": "A",
                    "content": ip_address,
                },
            }

        name = f"{subdomain}.{settings.DOMAIN}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{CloudflareService.BASE_URL}/zones/{settings.CLOUDFLARE_ZONE_ID}/dns_records",
                headers=CloudflareService._headers(),
                json={
                    "type": "A",
                    "name": name,
                    "content": ip_address,
                    "ttl": 120,
                    "proxied": proxy,
                },
            )
            data = resp.json()
            if not data.get("success"):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Cloudflare API error: {data.get('errors', [{}])[0].get('message', 'Unknown')}",
                )
            return {"success": True, "record": data["result"]}

    @staticmethod
    async def delete_dns_record(record_id: str) -> bool:
        """Remove a DNS record."""
        if not CloudflareService.is_configured():
            return True

        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{CloudflareService.BASE_URL}/zones/{settings.CLOUDFLARE_ZONE_ID}/dns_records/{record_id}",
                headers=CloudflareService._headers(),
            )
            return resp.json().get("success", False)
