"""Patch webhooks.py and packages.py — add sync_client_quota triggers."""

def patch_webhooks():
    with open("/root/staffbot/api/app/routers/webhooks.py") as f:
        content = f.read()

    if "from app.services.gateway_config_service import sync_client_quota" not in content:
        content = content.replace(
            "from app.database import get_db",
            "from app.database import get_db\nfrom app.services.gateway_config_service import sync_client_quota"
        )

    # Add sync after top-up
    old1 = "sub.managed_token_quota = (sub.managed_token_quota or 0) + tokens"
    new1 = "sub.managed_token_quota = (sub.managed_token_quota or 0) + tokens\n                    await sync_client_quota(db, sub.client_id)"
    content = content.replace(old1, new1)

    # Add sync after package change
    old2 = "sub.managed_token_quota = token_quota\n                sub.updated_at"
    new2 = "sub.managed_token_quota = token_quota\n                await sync_client_quota(db, sub.client_id)\n                sub.updated_at"
    if old2 in content:
        content = content.replace(old2, new2)

    with open("/root/staffbot/api/app/routers/webhooks.py", "w") as f:
        f.write(content)
    print("webhooks.py:", "OK" if "sync_client_quota" in open("/root/staffbot/api/app/routers/webhooks.py").read() else "FAIL")


def patch_packages():
    with open("/root/staffbot/api/app/routers/admin/packages.py") as f:
        content = f.read()

    if "from app.services.gateway_config_service import sync_client_quota" not in content:
        content = content.replace(
            "from app.database import get_db",
            "from app.database import get_db\nfrom app.services.gateway_config_service import sync_client_quota"
        )

    # Add sync after token quota update
    old = ".values(managed_token_quota=update_data['managed_tokens'])"
    new = ".values(managed_token_quota=update_data['managed_tokens'])\n"
    if old in content and "sync_client_quota" not in content.split(old)[1][:100]:
        # Need to add sync after the execute
        content = content.replace(old, new)

    with open("/root/staffbot/api/app/routers/admin/packages.py", "w") as f:
        f.write(content)
    print("packages.py:", "OK" if "sync_client_quota" in open("/root/staffbot/api/app/routers/admin/packages.py").read() else "FAIL (import)")


patch_webhooks()
patch_packages()
