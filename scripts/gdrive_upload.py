"""Upload the dated user-guide files to Google Drive.

The existing gcloud Application Default Credentials don't carry the Drive scope,
so this does a one-time browser consent (re-using the gcloud OAuth client) and
caches a Drive-scoped token at ~/.config/fastppm/gdrive_token.json for reuse.

It finds a folder whose name contains the target (default "FastPPM") and uploads
each file into it — updating in place if a same-named file already exists, so
re-runs don't create duplicates.

Run (interactively, so the browser consent can complete):
  ! .venv/bin/python -m scripts.gdrive_upload
  ! .venv/bin/python -m scripts.gdrive_upload --folder FastPPM <files…>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive"]
ADC = Path.home() / ".config/gcloud/application_default_credentials.json"
TOKEN = Path.home() / ".config/fastppm/gdrive_token.json"
ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

MIME = {".pdf": "application/pdf", ".md": "text/markdown",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".html": "text/html"}


def _default_files() -> list[Path]:
    """Newest dated guide trio: md / pdf / pptx."""
    pdfs = sorted(DOCS.glob("fastppm_user_guide_*.pdf"))
    if not pdfs:
        return []
    base = pdfs[-1].name.rsplit(".", 1)[0]  # e.g. fastppm_user_guide_2026-06-28
    return [DOCS / f"{base}{ext}" for ext in (".md", ".pdf", ".pptx")
            if (DOCS / f"{base}{ext}").exists()]


def _credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json())
            return creds
    # First run: consent in the browser, re-using the gcloud OAuth client.
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not ADC.exists():
        sys.exit(f"No credentials to bootstrap from: {ADC} not found.")
    d = json.loads(ADC.read_text())
    client = {"installed": {
        "client_id": d["client_id"], "client_secret": d["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}
    flow = InstalledAppFlow.from_client_config(client, SCOPES)
    # Don't auto-open a browser (it picks an arbitrary signed-in account); print the
    # URL so the user opens it in the right account. The local server still catches
    # the redirect on this machine.
    creds = flow.run_local_server(
        port=0, prompt="consent", open_browser=False,
        authorization_prompt_message=(
            "\n>>> Open this URL in a browser signed in to the right Google "
            "account, approve Drive access:\n\n{url}\n"))
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json())
    print(f"Saved Drive token → {TOKEN}")
    return creds


def _find_folder(svc, name: str) -> dict | None:
    res = svc.files().list(
        q=("mimeType='application/vnd.google-apps.folder' and trashed=false "
           f"and name contains '{name}'"),
        fields="files(id,name)", spaces="drive", pageSize=20,
        supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = res.get("files", [])
    if len(files) > 1:
        print("Multiple matching folders; using the first:")
        for f in files:
            print(f"  - {f['name']} ({f['id']})")
    return files[0] if files else None


def _upload(svc, folder_id: str, path: Path) -> dict:
    from googleapiclient.http import MediaFileUpload
    mime = MIME.get(path.suffix, "application/octet-stream")
    media = MediaFileUpload(str(path), mimetype=mime, resumable=True)
    # Update in place if a same-named file already lives in the folder.
    q = (f"name='{path.name}' and '{folder_id}' in parents and trashed=false")
    existing = svc.files().list(q=q, fields="files(id)", spaces="drive",
                                supportsAllDrives=True,
                                includeItemsFromAllDrives=True).execute().get("files", [])
    if existing:
        f = svc.files().update(fileId=existing[0]["id"], media_body=media,
                               fields="id,name,webViewLink",
                               supportsAllDrives=True).execute()
        f["_action"] = "updated"
        return f
    f = svc.files().create(body={"name": path.name, "parents": [folder_id]},
                           media_body=media, fields="id,name,webViewLink",
                           supportsAllDrives=True).execute()
    f["_action"] = "created"
    return f


def main(argv: list[str]) -> None:
    from googleapiclient.discovery import build
    folder_name = "FastPPM"
    args = list(argv)
    if "--folder" in args:
        i = args.index("--folder")
        folder_name = args[i + 1]
        del args[i:i + 2]
    files = [Path(a) for a in args] or _default_files()
    files = [f for f in files if f.exists()]
    if not files:
        sys.exit("No files to upload (none of the dated guide files were found).")

    creds = _credentials()
    svc = build("drive", "v3", credentials=creds)
    folder = _find_folder(svc, folder_name)
    if not folder:
        sys.exit(f"No Drive folder matching '{folder_name}'. "
                 "Create one (or pass --folder <name>) and re-run.")
    print(f"Uploading {len(files)} file(s) → Drive folder '{folder['name']}' "
          f"({folder['id']}):")
    for path in files:
        f = _upload(svc, folder["id"], path)
        print(f"  {f['_action']:8} {f['name']}  →  {f.get('webViewLink','')}")


if __name__ == "__main__":
    main(sys.argv[1:])
