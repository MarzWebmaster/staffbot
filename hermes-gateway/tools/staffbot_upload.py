#!/usr/bin/env python3
"""
StaffBot Upload Tools — Hermes Native Tool

Provides document upload and link extraction via StaffBot API.
Tools: upload_document, extract_link

All tools call the StaffBot API internally with GATEWAY_API_KEY for auth.
"""

import json
import os
import base64
import urllib.request
import urllib.error
from typing import Optional, Dict, Any


STAFFBOT_API_BASE = os.getenv("STAFFBOT_API_BASE", "http://staffbot-api:8000/api/v1")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")


def _api_request(method: str, path: str, client_id: int, body: Optional[Dict] = None) -> Dict[str, Any]:
    """Make an authenticated request to the StaffBot API."""
    url = f"{STAFFBOT_API_BASE}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Key": GATEWAY_API_KEY,
        "X-Client-ID": str(client_id),
    }
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"success": True, "data": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return {"success": False, "error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool Handlers ──────────────────────────────────────────────────────

def upload_document_handler(
    client_id: int,
    file_name: str,
    file_content_base64: str,
    mime_type: str = "",
) -> str:
    """
    Upload a document for AI analysis.
    
    The file content is base64-encoded. Supported formats: PDF, DOCX, TXT, PNG, JPG.
    """
    body = {
        "file_name": file_name,
        "file_content": file_content_base64,
        "mime_type": mime_type,
    }
    result = _api_request("POST", "/chat/upload", client_id, body)
    return json.dumps(result, ensure_ascii=False)


def extract_link_handler(client_id: int, url: str) -> str:
    """
    Extract and analyze content from a URL.
    
    Fetches the URL, extracts text content, and returns it for AI analysis.
    """
    body = {"url": url}
    result = _api_request("POST", "/chat/extract-link", client_id, body)
    return json.dumps(result, ensure_ascii=False)


# ── Requirement Check ──────────────────────────────────────────────────

def check_staffbot_upload_requirements() -> bool:
    """Check that StaffBot API is reachable and gateway key is set."""
    return bool(GATEWAY_API_KEY)


# ── OpenAI Function-Calling Schemas ────────────────────────────────────

UPLOAD_DOCUMENT_SCHEMA = {
    "name": "upload_document",
    "description": (
        "Upload a document (PDF, DOCX, TXT, image) for AI analysis. "
        "The file must be base64-encoded. Use this when the user sends a file "
        "and asks to analyze, summarize, or extract information from it. "
        "Supported formats: PDF, DOCX, TXT, PNG, JPG, JPEG."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "integer",
                "description": "The client ID (from system context — always pass this)."
            },
            "file_name": {
                "type": "string",
                "description": "Original filename (e.g., 'report.pdf', 'photo.jpg')."
            },
            "file_content_base64": {
                "type": "string",
                "description": "Base64-encoded file content."
            },
            "mime_type": {
                "type": "string",
                "description": "MIME type of the file (e.g., 'application/pdf', 'image/png')."
            }
        },
        "required": ["client_id", "file_name", "file_content_base64"]
    }
}

EXTRACT_LINK_SCHEMA = {
    "name": "extract_link",
    "description": (
        "Extract and analyze content from a URL/webpage. "
        "Use this when the user shares a link and asks 'what does this say?', "
        "'summarize this article', or 'extract info from this page'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "integer",
                "description": "The client ID (from system context — always pass this)."
            },
            "url": {
                "type": "string",
                "description": "The URL to extract content from."
            }
        },
        "required": ["client_id", "url"]
    }
}


# ── Registry ───────────────────────────────────────────────────────────

from tools.registry import registry, tool_error

registry.register(
    name="upload_document",
    toolset="staffbot",
    schema=UPLOAD_DOCUMENT_SCHEMA,
    handler=lambda args, **kw: upload_document_handler(
        client_id=args["client_id"],
        file_name=args["file_name"],
        file_content_base64=args.get("file_content_base64", ""),
        mime_type=args.get("mime_type", ""),
    ),
    check_fn=check_staffbot_upload_requirements,
    emoji="📎",
)

registry.register(
    name="extract_link",
    toolset="staffbot",
    schema=EXTRACT_LINK_SCHEMA,
    handler=lambda args, **kw: extract_link_handler(
        client_id=args["client_id"],
        url=args["url"],
    ),
    check_fn=check_staffbot_upload_requirements,
    emoji="🔗",
)
