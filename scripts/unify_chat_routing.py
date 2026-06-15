"""
Patch chat.py — route ALL traffic to Hermes :8642 (text + vision).
Removes the :8080 vision routing.
"""
with open("/root/staffbot/api/app/routers/chat.py") as f:
    content = f.read()

old_block = """    # ── 5. Route: Vision → Gateway :8080 (Mimo Omni) | Text → Hermes :8642 ─
    has_image = bool(data.image_base64)

    if has_image:
        # Vision route — use Mimo Omni via custom gateway
        target_url = f\"{GATEWAY_URL}/api/chat/send\"
        req_headers = {\"Content-Type\": \"application/json\", \"x-api-key\": GATEWAY_KEY}
        payload = {
            \"client_id\": client_id,
            \"container_id\": data.container_id,
            \"content\": data.content,
            \"provider\": \"mimo\",
            \"model\": \"mimo/mimo-v2-omni\",
            \"api_key\": data.api_key,
            \"image_base64\": data.image_base64,
            \"system_context\": system_context,
        }
    else:
        # Text route — Hermes Native with DeepSeek + tools
        target_url = f\"{HERMES_URL}/v1/chat/completions\"
        req_headers = {
            \"Content-Type\": \"application/json\",
            \"Authorization\": f\"Bearer {HERMES_KEY}\",
        }
        payload = {
            \"model\": data.model or \"deepseek-v4-flash\",
            \"messages\": [
                {
                    \"role\": \"system\",
                    \"content\": (
                        f\"You are an AI Staff agent for {current_user.name or 'Client'} \"
                        f\"({current_user.company or 'StaffBot'}). \"
                        f\"Client ID: {client_id}. \"
                        \"Be helpful, professional, and concise.\"
                    ),
                },
                {\"role\": \"user\", \"content\": data.content},
            ],
            \"max_tokens\": 2000,
        }"""

new_block = """    # ── 5. Route ALL traffic to Hermes Native :8642 (text + vision) ─
    has_image = bool(data.image_base64)

    if has_image:
        # Vision — use Mimo Omni via Hermes custom_providers
        user_content = [
            {\"type\": \"text\", \"text\": data.content},
            {\"type\": \"image_url\", \"image_url\": {\"url\": f\"data:image/png;base64,{data.image_base64}\"}},
        ]
        model_name = \"mimo/mimo-v2-omni\"
    else:
        # Text — use default model with tools
        user_content = data.content
        model_name = data.model or \"deepseek-v4-flash\"

    target_url = f\"{HERMES_URL}/v1/chat/completions\"
    req_headers = {
        \"Content-Type\": \"application/json\",
        \"Authorization\": f\"Bearer {HERMES_KEY}\",
    }
    payload = {
        \"model\": model_name,
        \"messages\": [
            {
                \"role\": \"system\",
                \"content\": (
                    f\"You are an AI Staff agent for {current_user.name or 'Client'} \"
                    f\"({current_user.company or 'StaffBot'}). \"
                    f\"Client ID: {client_id}. \"
                    \"Be helpful, professional, and concise.\"
                ),
            },
            {\"role\": \"user\", \"content\": user_content},
        ],
        \"max_tokens\": 2000,
    }"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open("/root/staffbot/api/app/routers/chat.py", "w") as f:
        f.write(content)
    print("OK — unified Hermes routing")
else:
    print("FAIL — old block not found")
    # Try finding the marker
    if "Route: Vision" in content:
        print("Found marker, trying alternative approach...")
