"""Streamlit front-end for the Fathom -> SOP pipeline.

Run locally with: streamlit run app.py
Deployed on Streamlit Community Cloud, secrets (ANTHROPIC_API_KEY,
FATHOM_API_KEY) are supplied via st.secrets and mirrored into the
environment so the existing src/config.py loader picks them up unchanged.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import streamlit as st

try:
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except Exception:
    pass  # no secrets.toml (e.g. local dev using .env instead) — fine

from src.config import load_settings
from src.fathom_client import FathomClient
from src.local_docx import create_sop_docx
from src.sop_generator import generate_sop
from src.video_frames import extract_frames

st.set_page_config(page_title="Fathom -> SOP Generator", page_icon="📋")
st.title("📋 Fathom → SOP Generator")
st.write(
    "Paste a Fathom recording link and get back a formatted, on-brand "
    "Standard Operating Procedure document."
)

recording_url = st.text_input(
    "Fathom recording URL", placeholder="https://fathom.video/calls/123456789"
)

with st.expander("Advanced options"):
    frame_interval = st.number_input(
        "Seconds between screenshots", min_value=5, max_value=60, value=15
    )
    crop_left = st.number_input(
        "Crop left (fraction)", min_value=0.0, max_value=0.3, value=0.018, step=0.005, format="%.3f"
    )
    crop_right = st.number_input(
        "Crop right (fraction)", min_value=0.0, max_value=0.5, value=0.285, step=0.005, format="%.3f"
    )
    crop_top = st.number_input(
        "Crop top (fraction)", min_value=0.0, max_value=0.5, value=0.265, step=0.005, format="%.3f"
    )
    crop_bottom = st.number_input(
        "Crop bottom (fraction)", min_value=0.0, max_value=0.5, value=0.125, step=0.005, format="%.3f"
    )

generate = st.button("Generate SOP", type="primary", disabled=not recording_url)

if generate:
    settings = load_settings()
    work_dir = Path(tempfile.mkdtemp(prefix="sop_"))
    status = st.status("Working...", expanded=True)
    try:
        fathom = FathomClient(settings.fathom_api_key)

        status.write("Resolving recording...")
        recording_id = fathom.resolve_recording_id(recording_url)

        status.write("Fetching transcript...")
        transcript = fathom.get_transcript(recording_id)
        summary = fathom.get_summary(recording_id)

        status.write("Requesting video download...")
        video_url = fathom.get_download_url(recording_id)
        video_path = work_dir / "video.mp4"
        status.write("Downloading video...")
        fathom.download_video(video_url, video_path)

        status.write(f"Extracting screenshots every {frame_interval}s...")
        frames = extract_frames(
            video_path,
            work_dir / "frames",
            interval_s=int(frame_interval),
            crop_left_fraction=crop_left,
            crop_right_fraction=crop_right,
            crop_top_fraction=crop_top,
            crop_bottom_fraction=crop_bottom,
        )
        status.write(f"Extracted {len(frames)} screenshots.")

        status.write("Generating SOP with Claude (this can take a minute)...")
        sop = generate_sop(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            transcript=transcript,
            summary=summary,
            frames=frames,
        )

        status.write("Writing document...")
        docx_path = create_sop_docx(sop, out_dir=work_dir / "output", source_url=recording_url)

        status.update(label="Done!", state="complete", expanded=False)

        st.success(f"Generated: **{sop.title}** ({len(sop.steps)} steps)")
        with open(docx_path, "rb") as f:
            st.download_button(
                "Download SOP (.docx)",
                data=f.read(),
                file_name=docx_path.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
    except Exception as e:  # noqa: BLE001 — surface any failure to the user, this is a UI boundary
        status.update(label="Failed", state="error")
        st.error(f"Something went wrong: {e}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
