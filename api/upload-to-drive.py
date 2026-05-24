#!/usr/bin/env python3
"""
Upload StaffBot API Backend code to Google Drive.
"""
import os, pickle, sys
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

FOLDER_ID = "1jB0Bj9Hv34PvYIlDtIofUapclsTD6-Zz"
SCOPE = ["https://www.googleapis.com/auth/drive.file"]
SCRIPT_DIR = "/home/marz/.hermes/profiles/staffbot/workspace/staffbot-proposal"
CRED_FILE = os.path.join(SCRIPT_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.pickle")
TAR_PATH = "/home/marz/staffbot/staffbot-api-backend.tar.gz"


def auth():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.expired and creds.refresh_token:
        print("[*] Refreshing expired token...")
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = Flow.from_client_secrets_file(CRED_FILE, scopes=SCOPE)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        print(f"[!] Open this URL:\n{auth_url}")
        code = input("[?] Enter authorization code: ").strip()
        flow.fetch_token(code=code)
        creds = flow.credentials
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return creds


def main():
    if not os.path.exists(TAR_PATH):
        print(f"[!] File not found: {TAR_PATH}")
        sys.exit(1)

    creds = auth()
    service = build("drive", "v3", credentials=creds)

    file_metadata = {
        "name": "staffbot-api-backend.tar.gz",
        "parents": [FOLDER_ID],
        "description": "StaffBot.my API Backend (FastAPI) — Full source code v1.0",
    }
    media = MediaFileUpload(TAR_PATH, mimetype="application/gzip", resumable=True)

    print("[*] Uploading to GDrive...")
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, size, webViewLink",
    ).execute()

    print(f"\n✅ Uploaded: {file['name']}")
    print(f"   Size: {int(file['size'])/1024:.1f} KB")
    print(f"   GDrive ID: {file['id']}")
    print(f"   Link: {file.get('webViewLink', 'N/A')}")


if __name__ == "__main__":
    main()
