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
timestamp; otherwise leave it null.

Accuracy is critical — this document will be followed literally, and a wrong technical value \
(a URL, field name, button label, ID, or setting) can break the process for whoever follows it. \
Only state a specific value if it is explicitly spoken in the transcript or clearly legible in a \
screenshot. Never substitute a value from general knowledge of what a step "usually" looks like, \
even if it seems like a more correct or more common choice — report what this specific recording \
actually shows and says, not what would typically be done.

The narrator will often use deictic references — "this", "that one", "like this", "here" — pointing \
at whatever is on screen at that moment instead of naming it. Resolve these by reading the exact \
text/value visible in the corresponding screenshot, not by guessing what they probably mean. If no \
screenshot is available at that moment or the value isn't legible, say so explicitly in the \
instruction or a note (e.g. "use the callback URL shown on screen at this step") rather than filling \
in a plausible-sounding value of your own.

Never attribute an invented detail to the transcript. A note like "per the narration..." or "as \
stated..." must only paraphrase something the transcript actually says — do not use that framing to \
add credibility to a value you inferred or assumed. If you are uncertain what a step's exact value \
is, write the instruction in general terms and flag the ambiguity in a note instead of asserting a \
specific answer.

If a meeting summary is provided below, treat it as a secondary, possibly-unreliable aid for overall \
structure only — it is itself AI-generated and can contain confidently-worded errors (e.g. inventing \
a specific value the speaker never actually said). The word-for-word transcript and the screenshots \
are the only ground truth. Never carry a specific value (a URL, name, ID, setting) from the summary \
into a step unless that same value also appears explicitly in the transcript or is legible on screen \
— if the summary states something the transcript doesn't support, ignore the summary's claim.

Call the emit_sop tool exactly once with the finished SOP."""


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
