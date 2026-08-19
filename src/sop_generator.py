"""Turns a Fathom transcript + extracted screenshots into a structured SOP,
using Claude's tool-use forcing to get reliable structured output.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

import anthropic

from .fathom_client import TranscriptLine
from .video_frames import Frame

SOP_TOOL = {
    "name": "emit_sop",
    "description": "Emit the finished Standard Operating Procedure.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "purpose": {"type": "string", "description": "1-2 sentence summary of what this SOP accomplishes."},
            "prerequisites": {"type": "array", "items": {"type": "string"}},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "integer"},
                        "instruction": {"type": "string"},
                        "screenshot_timestamp_s": {
                            "type": ["integer", "null"],
                            "description": "Timestamp in seconds of the extracted screenshot that best illustrates this step, or null if none apply.",
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["number", "instruction"],
                },
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "purpose", "steps"],
    },
}

SYSTEM_PROMPT = """You are a technical writer who converts screen-recorded walkthroughs into \
clear, numbered Standard Operating Procedures (SOPs). You are given a timestamped transcript \
of someone narrating a process, and a set of screenshots taken at fixed intervals through the \
video. Write concise, imperative-mood steps ("Click X", "Open Y"), skip filler and small talk, \
and merge narration that describes a single action into a single step. For each step, if one of \
the provided screenshots (by timestamp) clearly shows that step's UI state, reference its \
timestamp; otherwise leave it null. Call the emit_sop tool exactly once with the finished SOP."""


@dataclass
class SopStep:
    number: int
    instruction: str
    notes: str = ""
    screenshot_timestamp_s: int | None = None
    frame_path: str | None = None


@dataclass
class Sop:
    title: str
    purpose: str
    prerequisites: list[str] = field(default_factory=list)
    steps: list[SopStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _format_transcript(lines: list[TranscriptLine]) -> str:
    return "\n".join(f"[{l.timestamp}] {l.speaker}: {l.text}" for l in lines)


def _nearest_frame(timestamp_s: int | None, frames: list[Frame], tolerance_s: int = 20) -> Frame | None:
    if timestamp_s is None or not frames:
        return None
    nearest = min(frames, key=lambda f: abs(f.timestamp_s - timestamp_s))
    return nearest if abs(nearest.timestamp_s - timestamp_s) <= tolerance_s else None


def generate_sop(
    *,
    api_key: str,
    model: str,
    transcript: list[TranscriptLine],
    summary: str | None,
    frames: list[Frame],
) -> Sop:
    client = anthropic.Anthropic(api_key=api_key)

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                (f"Meeting summary:\n{summary}\n\n" if summary else "")
                + f"Transcript:\n{_format_transcript(transcript)}\n\n"
                + f"Below are {len(frames)} screenshots extracted at fixed intervals, "
                + "each labeled with its timestamp in seconds."
            ),
        }
    ]
    for frame in frames:
        content.append({"type": "text", "text": f"Screenshot at {frame.timestamp_s}s:"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(frame.path.read_bytes()).decode(),
                },
            }
        )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[SOP_TOOL],
        tool_choice={"type": "tool", "name": "emit_sop"},
        messages=[{"role": "user", "content": content}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    data = tool_use.input

    steps = []
    for raw_step in data.get("steps", []):
        ts = raw_step.get("screenshot_timestamp_s")
        frame = _nearest_frame(ts, frames)
        steps.append(
            SopStep(
                number=raw_step["number"],
                instruction=raw_step["instruction"],
                notes=raw_step.get("notes", ""),
                screenshot_timestamp_s=ts,
                frame_path=str(frame.path) if frame else None,
            )
        )

    return Sop(
        title=data["title"],
        purpose=data.get("purpose", ""),
        prerequisites=data.get("prerequisites", []),
        steps=steps,
        warnings=data.get("warnings", []),
    )
