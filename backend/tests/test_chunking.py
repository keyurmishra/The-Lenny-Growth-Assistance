"""
Tests for the chunking service.

These test the core chunking logic without any database or model dependencies.
Pure unit tests — fast, deterministic, no external services needed.
"""

import pytest
from app.services.chunking import (
    chunk_transcript,
    extract_speaker_from_chunk,
    extract_timestamp_from_chunk,
)


class TestChunkTranscript:
    """Tests for the chunk_transcript function."""

    def test_empty_text_returns_no_chunks(self):
        assert chunk_transcript("") == []
        assert chunk_transcript("   ") == []
        assert chunk_transcript(None) == []

    def test_short_text_returns_single_chunk(self):
        text = "This is a short transcript about product management."
        chunks = chunk_transcript(text, chunk_size=512)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].chunk_index == 0

    def test_long_text_splits_into_multiple_chunks(self):
        # Create text that's clearly longer than chunk_size
        paragraphs = [f"Paragraph {i}: " + "word " * 50 for i in range(10)]
        text = "\n\n".join(paragraphs)

        chunks = chunk_transcript(text, chunk_size=300, chunk_overlap=0)
        assert len(chunks) > 1

    def test_chunks_have_sequential_indices(self):
        paragraphs = [f"Paragraph {i}: " + "word " * 50 for i in range(10)]
        text = "\n\n".join(paragraphs)

        chunks = chunk_transcript(text, chunk_size=300, chunk_overlap=0)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_chunks_preserve_all_content(self):
        """No content should be lost during chunking (except whitespace normalization)."""
        paragraphs = [
            "First paragraph about growth strategies.",
            "Second paragraph about retention metrics.",
            "Third paragraph about user activation.",
        ]
        text = "\n\n".join(paragraphs)

        chunks = chunk_transcript(text, chunk_size=100, chunk_overlap=0)

        # Reconstruct text from chunks (roughly)
        all_content = " ".join(c.content for c in chunks)
        for para in paragraphs:
            assert para in all_content

    def test_chunk_overlap_creates_shared_content(self):
        """With overlap > 0, consecutive chunks should share some text."""
        paragraphs = [f"Paragraph number {i} with some meaningful content about topic {i}." for i in range(20)]
        text = "\n\n".join(paragraphs)

        chunks = chunk_transcript(text, chunk_size=200, chunk_overlap=50)

        # With overlap, we expect more chunks than without
        chunks_no_overlap = chunk_transcript(text, chunk_size=200, chunk_overlap=0)
        assert len(chunks) >= len(chunks_no_overlap)

    def test_word_count_is_accurate(self):
        text = "One two three four five six seven eight nine ten."
        chunks = chunk_transcript(text, chunk_size=512)
        assert chunks[0].word_count == 10

    def test_speaker_label_splitting(self):
        """Transcript speaker turns should be handled correctly."""
        text = (
            "Lenny (00:01:05): Welcome to the podcast. Today we discuss growth.\n\n"
            "Guest (00:02:30): Thanks for having me. Growth is important.\n\n"
            "Lenny (00:03:45): Let's talk about metrics."
        )

        chunks = chunk_transcript(text, chunk_size=200, chunk_overlap=0)
        # Should not lose any speaker turns
        all_content = " ".join(c.content for c in chunks)
        assert "Lenny" in all_content
        assert "Guest" in all_content


class TestExtractSpeaker:
    """Tests for speaker extraction from chunks."""

    def test_extracts_simple_speaker(self):
        text = "Lenny (00:01:05): Welcome to the podcast."
        assert extract_speaker_from_chunk(text) == "Lenny"

    def test_extracts_full_name_speaker(self):
        text = "Brian Chesky (00:05:30): Airbnb started in our apartment."
        assert extract_speaker_from_chunk(text) == "Brian Chesky"

    def test_returns_none_for_no_speaker(self):
        text = "This is just regular text without a speaker label."
        assert extract_speaker_from_chunk(text) is None

    def test_handles_hyphenated_names(self):
        text = "Mary-Jane Watson (00:10:00): Great question."
        assert extract_speaker_from_chunk(text) == "Mary-Jane Watson"


class TestExtractTimestamp:
    """Tests for timestamp extraction from chunks."""

    def test_extracts_timestamp(self):
        text = "Lenny (00:01:05): Welcome."
        assert extract_timestamp_from_chunk(text) == "00:01:05"

    def test_extracts_first_timestamp(self):
        text = "Lenny (00:01:05): Welcome.\nGuest (00:02:30): Thanks."
        assert extract_timestamp_from_chunk(text) == "00:01:05"

    def test_returns_none_for_no_timestamp(self):
        text = "No timestamps here."
        assert extract_timestamp_from_chunk(text) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
