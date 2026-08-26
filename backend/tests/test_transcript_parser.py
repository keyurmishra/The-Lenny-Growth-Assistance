"""
Tests for the transcript parser.

Tests YAML frontmatter parsing, content cleaning, and file discovery
without needing the actual transcript repo.
"""

import pytest
import tempfile
from pathlib import Path

from app.services.transcript_parser import (
    parse_transcript_file,
    discover_transcripts,
    _split_frontmatter,
    _clean_transcript_content,
)


class TestSplitFrontmatter:
    """Tests for YAML frontmatter splitting."""

    def test_splits_valid_frontmatter(self):
        raw = "---\nguest: Brian Chesky\ntitle: Test Episode\n---\nTranscript content here."
        metadata, content = _split_frontmatter(raw)

        assert metadata["guest"] == "Brian Chesky"
        assert metadata["title"] == "Test Episode"
        assert content.strip() == "Transcript content here."

    def test_no_frontmatter_returns_full_text(self):
        raw = "Just some text without frontmatter."
        metadata, content = _split_frontmatter(raw)

        assert metadata == {}
        assert content == raw

    def test_handles_multiline_values(self):
        raw = '---\nguest: Brian Chesky\ndescription: "A long description\\nthat spans lines"\n---\nContent.'
        metadata, content = _split_frontmatter(raw)

        assert metadata["guest"] == "Brian Chesky"
        assert "Content." in content

    def test_handles_empty_frontmatter(self):
        raw = "---\n---\nContent after empty frontmatter."
        metadata, content = _split_frontmatter(raw)

        assert metadata == {}
        assert "Content" in content


class TestCleanContent:
    """Tests for transcript content cleaning."""

    def test_collapses_excessive_newlines(self):
        text = "Para one.\n\n\n\n\nPara two."
        cleaned = _clean_transcript_content(text)
        assert "\n\n\n" not in cleaned
        assert "Para one." in cleaned
        assert "Para two." in cleaned

    def test_strips_line_whitespace(self):
        text = "  Leading spaces.  \n  More spaces.  "
        cleaned = _clean_transcript_content(text)
        assert cleaned.startswith("Leading")

    def test_removes_zero_width_characters(self):
        text = "Hello\u200bWorld\u200c"
        cleaned = _clean_transcript_content(text)
        assert "\u200b" not in cleaned
        assert "HelloWorld" in cleaned


class TestParseTranscriptFile:
    """Tests for full file parsing."""

    def test_parses_valid_transcript(self):
        content = """---
guest: Shreyas Doshi
title: "The art of decision making"
youtube_url: https://youtube.com/watch?v=abc123
publish_date: 2023-06-15
duration: "1:05:30"
duration_seconds: 3930
---

Lenny (00:01:05): Welcome to the podcast. Today we're talking about decisions.

Shreyas Doshi (00:01:30): Thanks Lenny. Decision making is one of the most important skills.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            episode_dir = Path(tmpdir) / "shreyas-doshi"
            episode_dir.mkdir()
            file_path = episode_dir / "transcript.md"
            file_path.write_text(content)

            result = parse_transcript_file(file_path)

        assert result is not None
        assert result.metadata.guest == "Shreyas Doshi"
        assert result.metadata.title == "The art of decision making"
        assert result.metadata.youtube_url == "https://youtube.com/watch?v=abc123"
        assert result.file_name == "shreyas-doshi"
        assert "decision making" in result.content.lower()

    def test_returns_none_for_missing_file(self):
        result = parse_transcript_file("/nonexistent/path/transcript.md")
        assert result is None

    def test_returns_none_for_empty_content(self):
        content = "---\nguest: Test\n---\n\n   \n\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test" / "transcript.md"
            file_path.parent.mkdir()
            file_path.write_text(content)

            result = parse_transcript_file(file_path)
        assert result is None

    def test_handles_missing_frontmatter_fields(self):
        content = "---\nguest: Minimal\n---\nSome content here."
        with tempfile.TemporaryDirectory() as tmpdir:
            episode_dir = Path(tmpdir) / "minimal"
            episode_dir.mkdir()
            file_path = episode_dir / "transcript.md"
            file_path.write_text(content)

            result = parse_transcript_file(file_path)

        assert result is not None
        assert result.metadata.guest == "Minimal"
        assert result.metadata.youtube_url == ""
        assert result.metadata.duration_seconds == 0


class TestDiscoverTranscripts:
    """Tests for transcript file discovery."""

    def test_discovers_transcripts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            episodes = Path(tmpdir)
            for name in ["alice", "bob", "charlie"]:
                d = episodes / name
                d.mkdir()
                (d / "transcript.md").write_text(f"---\nguest: {name}\n---\nContent.")

            paths = discover_transcripts(episodes)
            assert len(paths) == 3

    def test_returns_empty_for_missing_dir(self):
        paths = discover_transcripts("/nonexistent/directory")
        assert paths == []

    def test_ignores_non_transcript_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            episodes = Path(tmpdir)
            d = episodes / "test"
            d.mkdir()
            (d / "transcript.md").write_text("Content")
            (d / "notes.txt").write_text("Not a transcript")
            (d / "README.md").write_text("Not a transcript either")

            paths = discover_transcripts(episodes)
            assert len(paths) == 1
            assert paths[0].name == "transcript.md"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
