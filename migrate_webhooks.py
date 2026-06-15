"""
Standalone script: create client_webhooks table + indexes on the DB.
Run: python migrate_webhooks.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))

from app.services.client_webhook_migration import create_client_webhooks_table


async def main():
    print("Creating client_webhooks table...")
    await create_client_webhooks_table()
    print("✅ client_webhooks table ready")


if __name__ == "__main__":
    asyncio.run(main())
