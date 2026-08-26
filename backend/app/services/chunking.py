"""
Text chunking service for transcript ingestion.

DECISION: Custom chunker over LangChain's RecursiveCharacterTextSplitter
  LangChain's splitter is a 600-line class with 15 dependencies. Our needs
  are simple: split on paragraph boundaries, respect a max size, add overlap.
  Writing our own is ~80 lines, zero new dependencies, and fully transparent.

  TRADE-OFF: LangChain handles edge cases (code blocks, Markdown headers,
  HTML tags) that we don't. Our transcripts are conversational text with
  timestamps — none of those edge cases apply.

DECISION: Paragraph-aware splitting over fixed-character splitting
  Fixed-character splitting cuts mid-sentence, destroying context.
  Paragraph-aware splitting keeps speaker turns and thoughts intact.
  For podcast transcripts where each speaker turn is a natural paragraph,
  this preserves the conversational structure.

DECISION: Overlap of 50 characters
  Overlap prevents the case where a relevant answer spans two chunks and
  neither chunk alone contains enough context to be retrieved. 50 chars
  is ~1 sentence — enough to bridge the boundary without wasting tokens.
"""

import re
from dataclasses import dataclass


@dataclass
class TextChunk:
    """A chunk of text with its position metadata."""
    content: str
    chunk_index: int
    start_char: int
    end_char: int
    word_count: int

    def __repr__(self) -> str:
        preview = self.content[:80].replace("\n", " ")
        return f"<Chunk #{self.chunk_index} words={self.word_count} '{preview}...'>"


def chunk_transcript(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[TextChunk]:
    """
    Split transcript text into overlapping chunks, respecting paragraph boundaries.

    Strategy:
      1. Split text into paragraphs (double newline or speaker label boundaries)
      2. Accumulate paragraphs until adding the next would exceed chunk_size
      3. Emit the accumulated chunk
      4. Start the next chunk with overlap from the end of the previous

    Args:
        text: The full transcript text (without YAML frontmatter).
        chunk_size: Target maximum characters per chunk.
        chunk_overlap: Number of characters to overlap between consecutive chunks.

    Returns:
        List of TextChunk objects with content and position metadata.
    """
    if not text or not text.strip():
        return []

    # Split into paragraphs.
    # Podcast transcripts use double newlines and sometimes speaker labels like:
    #   "Lenny (00:03:56): ..."
    #   "Guest Name (00:05:12): ..."
    paragraphs = _split_into_paragraphs(text)

    if not paragraphs:
        return []

    chunks: list[TextChunk] = []
    current_content = ""
    current_start = 0
    char_offset = 0
    chunk_index = 0

    for para in paragraphs:
        para_stripped = para.strip()
        if not para_stripped:
            char_offset += len(para)
            continue

        # If adding this paragraph exceeds chunk_size and we have content,
        # emit the current chunk
        if current_content and (len(current_content) + len(para_stripped) + 1) > chunk_size:
            chunk = TextChunk(
                content=current_content.strip(),
                chunk_index=chunk_index,
                start_char=current_start,
                end_char=current_start + len(current_content),
                word_count=len(current_content.split()),
            )
            chunks.append(chunk)
            chunk_index += 1

            # Start next chunk with overlap from the end of the current chunk
            # Take the last `chunk_overlap` characters as the overlap seed
            if chunk_overlap > 0 and len(current_content) > chunk_overlap:
                # Find a word boundary near the overlap point
                overlap_text = current_content[-chunk_overlap:]
                space_idx = overlap_text.find(" ")
                if space_idx > 0:
                    overlap_text = overlap_text[space_idx + 1:]
                current_content = overlap_text + "\n\n"
                current_start = char_offset - len(overlap_text)
            else:
                current_content = ""
                current_start = char_offset

        # Accumulate
        if not current_content:
            current_start = char_offset

        if current_content:
            current_content += "\n\n" + para_stripped
        else:
            current_content = para_stripped

        char_offset += len(para)

    # Don't forget the last chunk
    if current_content.strip():
        chunk = TextChunk(
            content=current_content.strip(),
            chunk_index=chunk_index,
            start_char=current_start,
            end_char=current_start + len(current_content),
            word_count=len(current_content.split()),
        )
        chunks.append(chunk)

    return chunks


def _split_into_paragraphs(text: str) -> list[str]:
    """
    Split transcript text into paragraphs.

    Handles:
      - Double newline separation (standard Markdown)
      - Speaker label boundaries: "Name (HH:MM:SS): ..."
      - Single newlines before speaker labels (common in transcripts)

    DECISION: Treat each speaker turn as a separate paragraph
      This keeps one person's complete thought in a single unit, which is
      the most natural boundary for retrieval. If a speaker's turn is very
      long, it'll be split at the chunk_size boundary — which is fine because
      the overlap ensures continuity.
    """
    # First, normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Split on double newlines first (standard paragraph boundary)
    paragraphs = re.split(r"\n\s*\n", text)

    # Further split long paragraphs on speaker labels
    # Pattern: "Name (timestamp):" at the start of a line
    result = []
    speaker_pattern = re.compile(
        r"(?<=\n)(?=[A-Z][a-zA-Z\s\-\.]+\s*\(\d{2}:\d{2}:\d{2}\)\s*:)"
    )

    for para in paragraphs:
        # Check if this paragraph contains multiple speaker turns
        sub_parts = speaker_pattern.split(para)
        result.extend(sub_parts)

    return result


def extract_speaker_from_chunk(chunk_content: str) -> str | None:
    """
    Extract the speaker name from a chunk if it starts with a speaker label.

    Used for metadata enrichment — knowing who said something helps with
    questions like "What did Brian Chesky say about culture?"

    Returns:
        Speaker name or None if no speaker label is found.
    """
    match = re.match(
        r"^([A-Z][a-zA-Z\s\-\.]+)\s*\(\d{2}:\d{2}:\d{2}\)\s*:",
        chunk_content.strip(),
    )
    return match.group(1).strip() if match else None


def extract_timestamp_from_chunk(chunk_content: str) -> str | None:
    """
    Extract the first timestamp from a chunk.

    Useful for linking back to the specific moment in the YouTube video.

    Returns:
        Timestamp string "HH:MM:SS" or None.
    """
    match = re.search(r"\((\d{2}:\d{2}:\d{2})\)", chunk_content)
    return match.group(1) if match else None
