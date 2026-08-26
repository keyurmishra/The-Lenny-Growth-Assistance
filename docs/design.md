# Design — The Lenny Growth Assistant

## 1. Design Philosophy

This product is used by **knowledge workers under time pressure** — PMs, growth leads, and strategists who need answers they can trust and content they can use immediately. The design follows three principles:

1. **Reduce friction to zero.** The user should not need to learn a new tool. If they've used Claude or ChatGPT, the interface should feel immediately familiar.
2. **Show your work.** Every answer includes source citations. The design makes them accessible (one click) without cluttering the default view.
3. **Context stays visible.** When a document is generated, the chat doesn't disappear. The split-pane layout keeps both visible — the user can ask follow-up questions while reading the artifact.

---

## 2. Information Architecture

```
App
├── Sidebar (always visible, collapsible)
│   ├── Logo + App Name
│   ├── New Chat button
│   ├── Session list (recent conversations, truncated titles)
│   └── Active model badge (Ollama · llama3.2:3b)
│
├── Chat Panel (main workspace)
│   ├── Welcome screen (when no session active)
│   │   ├── Logo + tagline
│   │   └── 4 suggestion cards (2×2 grid)
│   ├── Message thread (when session active)
│   │   ├── User messages (right-aligned bubble)
│   │   ├── Assistant messages (left, with avatar)
│   │   │   ├── Markdown body
│   │   │   ├── [Open document] button (if artifact)
│   │   │   ├── [N sources] collapsible (if RAG response)
│   │   │   └── [Copy] button (hover-reveal)
│   │   └── Typing indicator (3 pulsing dots)
│   └── Input bar (always visible at bottom)
│       ├── Textarea (auto-expanding, max 200px)
│       └── Send button (↑ icon, dark when active)
│
└── Artifact Viewer (appears alongside chat when artifact exists)
    ├── Header: icon + title + type badge
    ├── Actions: Preview/Source toggle, Copy, Download, Close
    └── Content area
        ├── Markdown mode: ReactMarkdown + remark-gfm
        └── HTML mode: sandboxed iframe (srcdoc)
```

---

## 3. Visual Design System

### Color Palette (Claude-inspired warm neutrals)

| Token | Hex | Use |
|---|---|---|
| `surface.primary` | `#fafaf8` | Main background — warm off-white |
| `surface.secondary` | `#f4f4ef` | Slightly darker warm cream |
| `sidebar.bg` | `#f0efeb` | Sidebar background |
| `sidebar.hover` | `#e8e7e1` | Hover states |
| `sidebar.active` | `#e2e1da` | Active session |
| `ink.primary` | `#1a1916` | Main text — warm-tinted near-black |
| `ink.secondary` | `#44433e` | Secondary text |
| `ink.tertiary` | `#8a8880` | Muted text, placeholders |
| `accent.500` | `#d97706` | Brand orange (logo, avatar gradient, highlights) |
| `user.bubble` | `#eeede8` | User message background |

**Why warm neutrals instead of pure white/gray?**
Cool, high-contrast interfaces feel clinical. The warm palette creates a reading environment closer to paper — appropriate for a tool built around long-form content (podcast transcripts, essays). It mirrors Claude's visual identity intentionally, since the evaluator brief referenced "Claude Artifacts" as the reference design.

### Typography

| Use | Font | Weight | Size |
|---|---|---|---|
| Body / UI | Inter (Google Fonts) | 400, 500, 600 | 13–15px |
| Code blocks | JetBrains Mono | 400, 500 | 12–13px |

System font fallbacks: `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`

### Spacing & Radius

- Message padding: 16px horizontal, 12px vertical
- Input box: `border-radius: 16px` (pill-like, not sharp)
- Session items: `border-radius: 8px`
- Sidebar: 260px wide, collapses to 0 (no partial-width state)

---

## 4. Key Interaction States

### 4.1 Welcome State (no session selected)

- Centered layout with logo, tagline, and 4 suggestion cards
- Cards are clickable: clicking populates the input and creates a session
- Input bar is visible and active (user can type immediately)

### 4.2 Active Conversation

- **User message:** Right-aligned warm bubble, no avatar (saves space for content)
- **Assistant message:** Left-aligned, orange gradient avatar, full-width content
- **Loading state:** Avatar + 3 pulsing dots with staggered animation (not a spinner — dots feel more "thinking" than spinning)
- Messages auto-scroll to bottom on new content; user can scroll up to read history without being yanked back

### 4.3 Artifact Panel Open

- Chat panel shrinks to 50% width; artifact panel takes the other 50%
- Chat remains fully interactive — user can continue the conversation while viewing the artifact
- **Closing:** X button in artifact header → panel slides out, chat returns to full width
- **Reopening:** Amber "Open document →" button appears below the message that generated the artifact — always available regardless of how many messages have been sent since

### 4.4 Source Citations

- Collapsed by default (clean view)
- "N sources" button with BookOpen icon and chevron → opens inline below message
- Each source shows: episode title, guest, relevance %, and a 3-line excerpt
- Relevance % displayed as amber badge (warm color = trust signal)

### 4.5 Error States

- LLM timeout / error → assistant message with clear explanation and retry suggestion
- No relevant transcripts → assistant says "I don't have enough information in Lenny's transcripts to answer this" (not a generic error)
- Network failure → inline error in message thread (not a modal or toast)
- DB unavailable → health endpoint shows degraded; app still loads but chat fails gracefully

### 4.6 Sidebar Collapsed State

- Sidebar collapses to 0px width (no half-states)
- A `PanelLeft` icon appears in the top-left of the chat area to reopen
- No hamburger menu — same icon for open/close

---

## 5. Responsive Behavior

| Viewport | Behavior |
|---|---|
| ≥ 1200px | Sidebar (260px) + chat + artifact panel (50/50 split) |
| 768–1200px | Sidebar collapsible; artifact panel appears but compresses chat |
| < 768px | Sidebar hidden by default; artifact panel overlaps chat (not split) |

**Current implementation:** The layout uses CSS flex with fixed sidebar width and `w-1/2` split for the artifact panel. On smaller screens, the sidebar collapses and the artifact panel still renders. Full mobile optimization is out of scope for this version (documented in PRD scope exclusions).

---

## 6. Accessibility Considerations

| Concern | Implementation |
|---|---|
| Keyboard navigation | All interactive elements are native `<button>` or `<textarea>` — focus works without custom handling |
| Enter to send | Textarea intercepts `Enter` (without Shift) to submit; `Shift+Enter` adds a newline |
| ARIA labels | Send button, Close button, Copy button, Open sidebar all have `aria-label` |
| Color contrast | ink.primary (`#1a1916`) on surface.primary (`#fafaf8`) = 18.4:1 contrast ratio (WCAG AAA) |
| Focus indicators | Browser defaults preserved (not suppressed with `outline: none` globally) |
| Screen readers | `role="main"`, `aria-live` not yet implemented — acceptable for internal tool |

---

## 7. Design Decisions & Trade-offs

### Decision: No top header bar
Claude's interface has no fixed header — the sidebar toggle is inline. This gives the chat more vertical space, which matters when reading long assistant responses with code blocks. The model badge moves to the sidebar bottom.

### Decision: User messages are right-aligned bubbles, not full-width
Right-aligned bubbles visually distinguish "my words" from "the assistant's words" without needing role labels. It also makes short questions (which are most user inputs) look less sparse than a full-width row.

### Decision: Copy button is hover-revealed
Showing copy on every message creates visual clutter. Hover-reveal keeps the thread clean for reading while remaining discoverable for users who need it.

### Decision: Suggestion cards instead of example list
Cards are more scannable and feel clickable — they invite interaction rather than reading. The 2×2 grid covers the four main use cases: Q&A, retention, Ship30, metrics.

### Decision: Source citations are collapsible, not inline
Inline citations in the message body (like footnotes) disrupt reading flow. A collapsible "N sources" button after the message respects the reader's attention — they choose when to verify, not the interface.

### Decision: Artifact "Open document" button is persistent
Once closed, an artifact cannot be reopened from the header (it's gone). The button attached to the generating message is always available in the chat history, so the user can re-examine any artifact from any conversation.

### Decision: Warm off-white background, not pure white
Pure white (`#ffffff`) has a blue cast on most monitors that causes eye strain during extended reading sessions. The warm off-white (`#fafaf8`) is easier on the eyes and signals "document / reading environment" rather than "application form."
