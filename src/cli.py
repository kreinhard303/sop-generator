"""Entry point: python -m src.cli <fathom_url_or_recording_id> [options]"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .config import load_settings
from .fathom_client import FathomClient
from .local_docx import create_sop_docx
from .sop_generator import generate_sop
from .video_frames import extract_frames


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn a Fathom recording into an SOP document.")
    parser.add_argument("recording", help="Fathom recording ID, or a call/share URL containing one")
    parser.add_argument("--frame-interval", type=int, default=15, help="Seconds between extracted screenshots")
    parser.add_argument(
        "--crop-left",
        type=float,
        default=0.018,
        help="Fraction of frame width to crop off the left edge, to remove the black "
        "margin the shared window leaves against the screen edge (default: 0.018; "
        "pass 0 to disable)",
    )
    parser.add_argument(
        "--crop-right",
        type=float,
        default=0.285,
        help="Fraction of frame width to crop off the right edge, to remove Fathom's "
        "participant sidebar and the app's own scrollbar (default: 0.285; pass 0 to disable)",
    )
    parser.add_argument(
        "--crop-top",
        type=float,
        default=0.265,
        help="Fraction of frame height to crop off the top, to remove Fathom's black "
        "timestamp bar plus the browser's own tab/address/bookmarks chrome, stopping "
        "at the shared app's own UI (default: 0.265; pass 0 to disable)",
    )
    parser.add_argument(
        "--crop-bottom",
        type=float,
        default=0.125,
        help="Fraction of frame height to crop off the bottom, to remove the black "
        "band below the desktop taskbar (default: 0.125; pass 0 to disable)",
    )
    parser.add_argument("--keep-temp", action="store_true", help="Don't delete the downloaded video/frames afterward")
    parser.add_argument(
        "--output-dir", default="output", help="Where to write the local .docx (default: ./output)"
    )
    parser.add_argument(
        "--google",
        action="store_true",
        help="Also create a Google Doc (requires credentials/client_secret.json; see README)",
    )
    args = parser.parse_args()

    settings = load_settings()
    fathom = FathomClient(settings.fathom_api_key)

    print("Resolving recording ID...")
    recording_id = fathom.resolve_recording_id(args.recording)
    work_dir = settings.temp_dir / recording_id

    try:
        print(f"Fetching transcript for recording {recording_id}...")
        transcript = fathom.get_transcript(recording_id)

        print("Requesting video download from Fathom...")
        video_url = fathom.get_download_url(recording_id)
        video_path = work_dir / "video.mp4"
        print("Downloading video...")
        fathom.download_video(video_url, video_path)

        print(f"Extracting screenshots every {args.frame_interval}s...")
        frames = extract_frames(
            video_path,
            work_dir / "frames",
            interval_s=args.frame_interval,
            crop_left_fraction=args.crop_left,
            crop_right_fraction=args.crop_right,
            crop_top_fraction=args.crop_top,
            crop_bottom_fraction=args.crop_bottom,
        )
        print(f"Extracted {len(frames)} screenshots.")

        print("Generating SOP with Claude...")
        sop = generate_sop(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            transcript=transcript,
            frames=frames,
        )
        print(f"Generated SOP with {len(sop.steps)} steps.")

        print("Writing local .docx...")
        docx_path = create_sop_docx(sop, out_dir=Path(args.output_dir), source_url=args.recording)
        print(f"\nSaved: {docx_path.resolve()}")

        if args.google:
            from .google_docs import create_sop_doc

            print("Creating Google Doc...")
            doc_url = create_sop_doc(
                sop,
                client_secret_path=settings.google_client_secret_path,
                token_path=settings.google_token_path,
            )
            print(f"Google Doc: {doc_url}")
        return 0
    finally:
        if not args.keep_temp and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
