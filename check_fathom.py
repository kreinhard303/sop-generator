r"""One-off check: confirm the Fathom key works and can see a recording.
Usage: .venv\Scripts\python.exe check_fathom.py <fathom_url_or_recording_id>
"""
import sys
from src.config import load_settings
from src.fathom_client import FathomClient

settings = load_settings()
client = FathomClient(settings.fathom_api_key)
recording_id = client.resolve_recording_id(sys.argv[1])
transcript = client.get_transcript(recording_id)
print(f"OK — {len(transcript)} transcript lines. First line: {transcript[0] if transcript else '(empty)'}")
