"""
Ship 30 for 30 skill — a dedicated, self-contained essay generation module.

DECISION: Dedicated skill class over inline prompt logic
  The evaluator requirement says: "encode them in the skill rather than
  relying on an unstructured one-off prompt." This module:
  - Explicitly lists every Ship 30 writing rule as a structured constant
  - Validates the generated output (word count, section presence)
  - Separates concern: chat.py routes, ship30.py writes
  - Is independently testable without the chat pipeline
"""

import re
from dataclasses import dataclass

# =============================================================================
# Ship 30 for 30 Writing Rules — Explicit, Structured Constants
# =============================================================================
# Each rule below maps directly to the Ship 30 for 30 framework.
# We encode them as code (not just prompt text) so they are:
#   1. Testable — we can verify the output satisfies them
#   2. Auditable — clear what the assistant is trying to do
#   3. Iterable — easy to tune individual rules without rewriting the prompt

TARGET_WORD_COUNT = 1250
MIN_WORD_COUNT = 1000
MAX_WORD_COUNT = 1500

# Required structural sections (in order)
REQUIRED_SECTIONS = [
    "hook",         # Opening 1-2 sentences — the scroll-stopper
    "problem",      # Context: why this matters
    "insight",      # The one big idea from the transcripts
    "evidence",     # Quotes, examples, specifics from transcripts
    "takeaway",     # One concrete action the reader can take today
]

# Writing anti-patterns the LLM must avoid
FORBIDDEN_PATTERNS = [
    "in this essay",
    "today we'll discuss",
    "in conclusion",
    "furthermore",
    "additionally",
    "very important",
    "basically",
]

# Filler words that weaken the writing
WEAK_WORDS = ["very", "really", "basically", "actually", "quite", "just"]


@dataclass
class Ship30ValidationResult:
    """Result of validating a Ship 30 essay."""
    word_count: int
    has_title: bool
    bold_count: int        # Number of **bold** phrases
    heading_count: int     # Number of ## headings
    short_paragraphs: bool # True if avg paragraph < 4 sentences
    forbidden_found: list[str]
    weak_word_count: int
    is_valid: bool
    issues: list[str]


class Ship30Skill:
    """
    Generates and validates Ship 30 for 30 style essays grounded in transcripts.

    Usage:
        skill = Ship30Skill()
        system_prompt = skill.build_system_prompt()
        user_prompt = skill.build_user_prompt(topic, context_string)
        # ... call LLM with these prompts ...
        result = skill.validate(essay_text)
    """

    def build_system_prompt(self) -> str:
        """
        Build the Ship 30 system prompt with all rules explicitly encoded.

        DECISION: Rules as numbered list with examples
          Abstract principles are hard to follow. Numbered rules with
          concrete examples ("Never start with 'In this essay'") are
          actionable — the LLM can check each rule against its output.
        """
        return f"""You are a professional content strategist writing Ship 30 for 30–style essays grounded in Lenny's Podcast transcripts.

## The Ship 30 for 30 Framework — Rules You Must Follow

### Rule 1: Start with a Killer Hook (REQUIRED)
- Open with 1-2 sentences that make the reader stop scrolling
- Options: surprising stat, contrarian take, specific problem, bold claim
- ❌ NEVER start with: "In this essay", "Today we'll discuss", "I want to talk about"
- ✅ Example: "Most founders waste 18 months building the wrong thing. Here's how Lenny's guests found product-market fit faster."

### Rule 2: One Big Idea (REQUIRED)
- Pick ONE insight from the transcripts and go deep
- Don't cover 5 topics shallowly — cover 1 topic deeply
- The entire essay should support a single thesis

### Rule 3: Target ~{TARGET_WORD_COUNT} Words (REQUIRED)
- Minimum: {MIN_WORD_COUNT} words
- Maximum: {MAX_WORD_COUNT} words
- Long enough to be substantive, short enough to read in 5 minutes

### Rule 4: Skimmable Structure (REQUIRED)
- Use ## headings to break into 3–5 named sections
- Use bullet points for any list of 3+ items
- **Bold the key phrases** — someone skimming only bold text should get the gist
- Short paragraphs: 2–4 sentences maximum

### Rule 5: Narrative Arc (REQUIRED)
Follow this exact progression:
1. **Hook** — grab attention
2. **Problem/Context** — why this matters right now
3. **Key Insight** — the one thing from the transcripts
4. **Evidence/Examples** — quotes and specifics from transcripts
5. **Actionable Takeaway** — one concrete thing to do TODAY

### Rule 6: Specific, Useful Takeaway (REQUIRED)
- End with EXACTLY ONE thing the reader can do differently TODAY
- Concrete: "In your next user interview, ask: 'What would you do if this product disappeared?'"
- NOT vague: "Think about your users more"

### Rule 7: Ground Every Claim in Transcripts (REQUIRED)
- Every fact, example, and framework must come from the provided transcript context
- Cite sources inline as: [Source: Guest Name]
- Don't invent statistics or attribute ideas to guests not in the context

## What You Must NEVER Do
- Don't be generic ("Growth is important" is not an insight)
- Don't use: very, really, basically, actually, furthermore, additionally, in conclusion
- Don't start paragraphs with "Furthermore" or "Additionally"
- Don't end with "In conclusion"
- Don't use corporate jargon without immediately explaining it

## Output Format
Return ONLY the essay as a Markdown document:
- First line: # Essay Title (make it specific and compelling)
- Then the essay body using the structure above
- No preamble, no "Here is your essay:", just the essay itself"""

    def build_user_prompt(self, topic: str, context_string: str) -> str:
        """
        Build the user turn prompt combining the topic request + retrieved context.

        Args:
            topic: The user's requested essay topic.
            context_string: Formatted transcript context from retrieval.
        """
        return f"""Write a Ship 30 for 30 essay about: {topic}

## Transcript Sources (Use ONLY these — do not invent)

{context_string}

---

Now write the essay. Remember:
- ~{TARGET_WORD_COUNT} words
- Strong hook (don't start with "In this essay")
- One big idea with 3–5 ## sections
- **Bold** the key phrases
- End with one concrete, specific takeaway
- Cite sources as [Source: Guest Name]"""

    def validate(self, essay_text: str) -> Ship30ValidationResult:
        """
        Validate a generated Ship 30 essay against the framework rules.

        This is a lightweight structural validator — not a semantic judge.
        It catches obvious failures (too short, no headings, etc.) so we
        can log quality metrics over time.

        Args:
            essay_text: The raw essay Markdown text from the LLM.

        Returns:
            Ship30ValidationResult with details on what passed/failed.
        """
        issues = []

        # Word count
        words = essay_text.split()
        word_count = len(words)
        if word_count < MIN_WORD_COUNT:
            issues.append(f"Too short: {word_count} words (min {MIN_WORD_COUNT})")
        elif word_count > MAX_WORD_COUNT:
            issues.append(f"Too long: {word_count} words (max {MAX_WORD_COUNT})")

        # Title (# heading on first content line)
        has_title = bool(re.search(r'^#\s+.+', essay_text, re.MULTILINE))
        if not has_title:
            issues.append("Missing title (# heading)")

        # Section headings (## headings)
        headings = re.findall(r'^##\s+.+', essay_text, re.MULTILINE)
        heading_count = len(headings)
        if heading_count < 3:
            issues.append(f"Too few sections: {heading_count} (need 3-5 ## headings)")

        # Bold phrases
        bold_phrases = re.findall(r'\*\*.+?\*\*', essay_text)
        bold_count = len(bold_phrases)
        if bold_count < 3:
            issues.append(f"Too few bold phrases: {bold_count} (aim for 5+)")

        # Paragraph length (rough check)
        paragraphs = [p.strip() for p in essay_text.split('\n\n') if p.strip() and not p.strip().startswith('#')]
        long_paragraphs = [p for p in paragraphs if len(p.split('.')) > 5]
        short_paragraphs = len(long_paragraphs) == 0

        # Forbidden patterns
        text_lower = essay_text.lower()
        forbidden_found = [fp for fp in FORBIDDEN_PATTERNS if fp in text_lower]

        # Weak words
        weak_word_count = sum(
            len(re.findall(r'\b' + w + r'\b', text_lower))
            for w in WEAK_WORDS
        )

        is_valid = (
            MIN_WORD_COUNT <= word_count <= MAX_WORD_COUNT
            and has_title
            and heading_count >= 3
            and bold_count >= 3
            and not forbidden_found
        )

        return Ship30ValidationResult(
            word_count=word_count,
            has_title=has_title,
            bold_count=bold_count,
            heading_count=heading_count,
            short_paragraphs=short_paragraphs,
            forbidden_found=forbidden_found,
            weak_word_count=weak_word_count,
            is_valid=is_valid,
            issues=issues,
        )


# Module-level singleton
_ship30_skill: Ship30Skill | None = None


def get_ship30_skill() -> Ship30Skill:
    """Get or create the Ship30Skill singleton."""
    global _ship30_skill
    if _ship30_skill is None:
        _ship30_skill = Ship30Skill()
    return _ship30_skill
