"""Thin wrapper around the Fathom API (https://developers.fathom.ai).

Covers the three calls this tool needs: transcript, summary, and the
request-download / poll-download / download-file flow for the raw video.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.fathom.ai/external/v1"

# Public Fathom URLs embed a call ID or share token that is NOT the same as
# the internal recording_id the API needs — e.g. /calls/789858790 resolves to
# recording_id 174523222. Resolution requires listing /meetings and matching
# on the `url` or `share_url` field (there is no direct lookup-by-URL endpoint).
_CALL_ID_IN_URL = re.compile(r"/calls/(\d+)")
_SHARE_TOKEN_IN_URL = re.compile(r"/share/(?:[a-z]/)?([A-Za-z0-9_-]+)")


class FathomAPIError(RuntimeError):
    pass


class DownloadTimeoutError(FathomAPIError):
    pass


class RecordingNotFoundError(FathomAPIError):
    pass


@dataclass
class TranscriptLine:
    speaker: str
    text: str
    timestamp: str  # "HH:MM:SS"

    def seconds(self) -> int:
        h, m, s = (int(part) for part in self.timestamp.split(":"))
        return h * 3600 + m * 60 + s


class FathomClient:
    def __init__(self, api_key: str, timeout: int = 30):
        self._session = requests.Session()
        self._session.headers["X-Api-Key"] = api_key
        self._timeout = timeout

    def _get(self, path: str, **kwargs: Any) -> dict:
        resp = self._session.get(f"{BASE_URL}{path}", timeout=self._timeout, **kwargs)
        if not resp.ok:
            raise FathomAPIError(f"GET {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def _post(self, path: str, **kwargs: Any) -> dict:
        resp = self._session.post(f"{BASE_URL}{path}", timeout=self._timeout, **kwargs)
        if not resp.ok:
            raise FathomAPIError(f"POST {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def resolve_recording_id(self, url_or_id: str, *, max_pages: int = 20) -> str:
        """Accept a bare recording_id or a Fathom call/share URL and return the
        internal recording_id. Public URLs embed a different ID than the API's
        recording_id, so a URL is resolved by paginating /meetings and matching
        its `url` or `share_url` field.
        """
        candidate = url_or_id.strip()
        if candidate.isdigit():
            return candidate

        call_match = _CALL_ID_IN_URL.search(candidate)
        if call_match:
            return self._find_recording_id(field="url", needle=call_match.group(1), max_pages=max_pages)

        share_match = _SHARE_TOKEN_IN_URL.search(candidate)
        if share_match:
            return self._find_recording_id(field="share_url", needle=share_match.group(1), max_pages=max_pages)

        raise ValueError(
            f"Couldn't parse a call ID or share token out of {url_or_id!r}. "
            "Pass a bare recording ID or a Fathom call/share URL."
        )

    def _find_recording_id(self, *, field: str, needle: str, max_pages: int) -> str:
        cursor: str | None = None
        for _ in range(max_pages):
            params = {"limit": 50}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/meetings", params=params)
            for item in data.get("items", []):
                if needle in (item.get(field) or ""):
                    return str(item["recording_id"])
            cursor = data.get("next_cursor")
            if not cursor:
                break
        raise RecordingNotFoundError(
            f"Couldn't find a recording with {field} containing {needle!r} "
            f"in the first {max_pages} pages of /meetings."
        )

    def get_transcript(self, recording_id: str) -> list[TranscriptLine]:
        data = self._get(f"/recordings/{recording_id}/transcript")
        items = data if isinstance(data, list) else data.get("items", data.get("transcript", []))
        return [
            TranscriptLine(
                speaker=item.get("speaker", {}).get("display_name", "Unknown"),
                text=item.get("text", ""),
                timestamp=item.get("timestamp", "00:00:00"),
            )
            for item in items
        ]

    def get_summary(self, recording_id: str) -> str | None:
        try:
            data = self._get(f"/recordings/{recording_id}/summary")
        except FathomAPIError:
            return None
        return data.get("summary") or data.get("markdown_formatted") or None

    def get_download_url(
        self, recording_id: str, *, interval_s: float = 5.0, timeout_s: float = 600.0
    ) -> str:
        """Request a video download and return its URL, polling if necessary.

        POST /recordings/{id}/download can return the finished download inline
        (status "completed" with a video.url already present) for short
        recordings, or a pending download that must be polled at
        GET /recordings/{id}/downloads/{download_id} — a recording-scoped path,
        not the top-level /downloads/{id} the API reference implies.
        """
        data = self._post(f"/recordings/{recording_id}/download")
        download_id = data.get("download_id") or data.get("id")
        if not download_id:
            raise FathomAPIError(f"No download_id in response: {data}")

        url = self._extract_video_url(data)
        if url:
            return url

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            data = self._get(f"/recordings/{recording_id}/downloads/{download_id}")
            status = (data.get("status") or "").lower()
            if status in ("complete", "completed", "ready", "done"):
                url = self._extract_video_url(data)
                if not url:
                    raise FathomAPIError(f"Download marked complete but no URL: {data}")
                return url
            if status in ("failed", "error"):
                raise FathomAPIError(f"Download failed: {data}")
            time.sleep(interval_s)
        raise DownloadTimeoutError(f"Download {download_id} did not complete within {timeout_s}s")

    @staticmethod
    def _extract_video_url(data: dict) -> str | None:
        return (
            (data.get("video") or {}).get("url")
            or data.get("url")
            or data.get("download_url")
        )

    def download_video(self, video_url: str, dest_path: Path) -> Path:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        # Use a plain request (no X-Api-Key): video_url is typically a
        # pre-signed CDN/S3 URL that will reject unexpected auth headers.
        with requests.get(video_url, stream=True, timeout=self._timeout) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        return dest_path
