"""Creates a formatted Google Doc from a generated SOP, with inline screenshots.

Uses an installed-app OAuth flow (browser consent on first run, cached token
after that) and the narrower `drive.file` scope, since the tool only ever
touches files it creates itself.
"""
from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .sop_generator import Sop

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def get_credentials(client_secret_path: Path, token_path: Path) -> Credentials:
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_path.exists():
                raise RuntimeError(
                    f"Missing Google OAuth client secret at {client_secret_path}. "
                    "See README.md for how to create one."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
    return creds


def _upload_temp_image(drive, path: str) -> tuple[str, str]:
    """Upload an image to Drive, make it link-viewable, return (file_id, url)."""
    file = drive.files().create(
        body={"name": Path(path).name}, media_body=MediaFileUpload(path), fields="id"
    ).execute()
    file_id = file["id"]
    drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}).execute()
    return file_id, f"https://drive.google.com/uc?id={file_id}"


def create_sop_doc(sop: Sop, *, client_secret_path: Path, token_path: Path) -> str:
    creds = get_credentials(client_secret_path, token_path)
    docs = build("docs", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    doc = docs.documents().create(body={"title": sop.title}).execute()
    doc_id = doc["documentId"]

    requests: list[dict] = []
    heading_ranges: list[tuple[int, int]] = []  # (start, end) to style as HEADING_2
    uploaded_file_ids: list[str] = []
    index = 1

    def insert_text(text: str, *, heading: bool = False) -> None:
        nonlocal index
        requests.append({"insertText": {"location": {"index": index}, "text": text}})
        if heading:
            heading_ranges.append((index, index + len(text.rstrip("\n"))))
        index += len(text)

    insert_text(sop.title + "\n", heading=True)
    if sop.purpose:
        insert_text(sop.purpose + "\n\n")

    if sop.prerequisites:
        insert_text("Prerequisites\n", heading=True)
        for item in sop.prerequisites:
            insert_text(f"• {item}\n")
        insert_text("\n")

    insert_text("Steps\n", heading=True)
    for step in sop.steps:
        insert_text(f"{step.number}. {step.instruction}\n")
        if step.notes:
            insert_text(f"    Note: {step.notes}\n")
        if step.frame_path:
            file_id, url = _upload_temp_image(drive, step.frame_path)
            uploaded_file_ids.append(file_id)
            requests.append(
                {
                    "insertInlineImage": {
                        "location": {"index": index},
                        "uri": url,
                        "objectSize": {
                            "height": {"magnitude": 250, "unit": "PT"},
                            "width": {"magnitude": 400, "unit": "PT"},
                        },
                    }
                }
            )
            index += 1
            insert_text("\n")
        insert_text("\n")

    if sop.warnings:
        insert_text("Warnings\n", heading=True)
        for item in sop.warnings:
            insert_text(f"• {item}\n")

    for start, end in heading_ranges:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    "fields": "namedStyleType",
                }
            }
        )

    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    for file_id in uploaded_file_ids:
        drive.files().delete(fileId=file_id).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"
