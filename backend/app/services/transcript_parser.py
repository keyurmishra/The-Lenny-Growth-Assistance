"""
Transcript parser — reads Lenny's Podcast transcript files.

Each transcript is a Markdown file with YAML frontmatter:

    ---
    guest: Brian Chesky
    title: "The full story of Airbnb | Brian Chesky"
    youtube_url: https://www.youtube.com/watch?v=...
    publish_date: 2023-05-15
    duration: "1:23:45"
    ---

    Lenny (00:01:05): Welcome to Lenny's Podcast...
    Brian Chesky (00:02:30): Thanks for having me...

DECISION: Manual YAML+content split over PyYAML's multi-doc parser
  PyYAML's load_all() can handle frontmatter, but it's finicky with
  transcripts that contain YAML-like characters (colons after timestamps).
  A simple split on '---' is more robust for this specific format.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TranscriptMetadata:
    """Parsed metadata from transcript YAML frontmatter."""
    guest: str = "Unknown"
    title: str = ""
    youtube_url: str = ""
    video_id: str = ""
    publish_date: str = ""
    duration: str = ""
    duration_seconds: int = 0
    description: str = ""
    view_count: int = 0
    channel: str = "Lenny's Podcast"
    file_path: str = ""

    def to_dict(self) -> dict:
        """Convert to a dict for storage in JSONB metadata columns."""
        return {
            "guest": self.guest,
            "title": self.title,
            "youtube_url": self.youtube_url,
            "video_id": self.video_id,
            "publish_date": self.publish_date,
            "duration": self.duration,
        }


@dataclass
class ParsedTranscript:
    """A fully parsed transcript file."""
    metadata: TranscriptMetadata
    content: str  # The transcript text (without frontmatter)
    file_name: str  # The guest directory name (e.g., "brian-chesky")

    @property
    def display_name(self) -> str:
        """Human-readable name for this transcript."""
        if self.metadata.title:
            return self.metadata.title
        return self.file_name.replace("-", " ").title()


def parse_transcript_file(file_path: str | Path) -> ParsedTranscript | None:
    """
    Parse a single transcript Markdown file.

    Args:
        file_path: Path to the transcript.md file.

    Returns:
        ParsedTranscript object, or None if the file is unparseable.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        logger.warning("transcript_not_found", path=str(file_path))
        return None

    try:
        raw = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Some files might have non-UTF-8 encoding
        try:
            raw = file_path.read_text(encoding="latin-1")
        except Exception as e:
            logger.error("transcript_read_error", path=str(file_path), error=str(e))
            return None

    # Split frontmatter from content
    metadata, content = _split_frontmatter(raw)

    if not content or not content.strip():
        logger.warning("transcript_empty_content", path=str(file_path))
        return None

    # Clean the content
    content = _clean_transcript_content(content)

    # Extract the guest directory name
    # Path like: .../episodes/brian-chesky/transcript.md
    file_name = file_path.parent.name

    # Build metadata object
    meta = TranscriptMetadata(
        guest=metadata.get("guest", file_name.replace("-", " ").title()),
        title=metadata.get("title", ""),
        youtube_url=metadata.get("youtube_url", ""),
        video_id=metadata.get("video_id", ""),
        publish_date=str(metadata.get("publish_date", "")),
        duration=str(metadata.get("duration", "")),
        duration_seconds=int(metadata.get("duration_seconds", 0) or 0),
        description=metadata.get("description", ""),
        view_count=int(metadata.get("view_count", 0) or 0),
        channel=metadata.get("channel", "Lenny's Podcast"),
        file_path=str(file_path),
    )

    return ParsedTranscript(
        metadata=meta,
        content=content,
        file_name=file_name,
    )


def _split_frontmatter(raw_text: str) -> tuple[dict, str]:
    """
    Split YAML frontmatter from Markdown content.

    Expected format:
        ---
        key: value
        ---
        Content here...

    Returns:
        Tuple of (metadata_dict, content_string).
        Returns ({}, full_text) if no frontmatter is found.
    """
    # Match frontmatter block at the start of the file
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", raw_text, re.DOTALL)

    if not match:
        # No frontmatter — treat entire file as content
        return {}, raw_text

    frontmatter_str = match.group(1)
    content = match.group(2)

    try:
        metadata = yaml.safe_load(frontmatter_str) or {}
    except yaml.YAMLError as e:
        logger.warning("frontmatter_parse_error", error=str(e))
        metadata = {}

    return metadata, content


def _clean_transcript_content(content: str) -> str:
    """
    Clean transcript text for better chunking and retrieval.

    Operations:
      - Remove excessive whitespace
      - Normalize newlines
      - Strip any remaining Markdown artifacts that don't add value for search
      - Keep timestamps (they're useful for source linking)

    DECISION: Minimal cleaning over aggressive normalization
      Transcripts are already fairly clean from the repo. Over-cleaning
      (e.g., removing all timestamps, lowercasing) would destroy useful
      information. We keep the text as close to original as possible.
    """
    # Normalize line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse 3+ consecutive newlines into 2
    content = re.sub(r"\n{3,}", "\n\n", content)

    # Remove leading/trailing whitespace per line (but keep newlines)
    lines = [line.strip() for line in content.split("\n")]
    content = "\n".join(lines)

    # Remove any zero-width characters
    content = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", content)

    return content.strip()


def discover_transcripts(episodes_dir: str | Path) -> list[Path]:
    """
    Find all transcript.md files in the episodes directory.

    Expected structure:
        episodes/
        ├── brian-chesky/
        │   └── transcript.md
        ├── shreyas-doshi/
        │   └── transcript.md
        └── ...

    Returns:
        Sorted list of paths to transcript.md files.
    """
    episodes_dir = Path(episodes_dir)

    if not episodes_dir.exists():
        logger.error("episodes_dir_not_found", path=str(episodes_dir))
        return []

    transcripts = sorted(episodes_dir.glob("*/transcript.md"))
    logger.info("transcripts_discovered", count=len(transcripts), path=str(episodes_dir))

    return transcripts
