# Manual Test Plan — The Lenny Growth Assistant

## Overview

This document outlines manual tests for verifying the UI and end-to-end user experience. Run these after the automated test suite passes.

**Prerequisites:**
- All services running (`docker-compose up`)
- Transcripts ingested (`python scripts/ingest.py`)
- Ollama model pulled (`ollama pull  llama3.2:3b`)

---

## 1. Session Management

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 1.1 | Create new session | Click "New Chat" button | New empty chat appears, sidebar shows new session |
| 1.2 | Session persistence | Send a message, refresh the page | Messages are still visible after reload |
| 1.3 | Multiple sessions | Create 3 sessions, switch between them | Each session shows its own messages independently |
| 1.4 | Session title | Send first message "What is PMF?" | Session title in sidebar updates to show the question |
| 1.5 | Delete session | Click delete on a session | Session removed from sidebar, chat area clears |

## 2. Grounded Q&A (RAG)

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 2.1 | Basic question | Ask "What does Lenny say about product-market fit?" | Response includes specific insights with source citations [Source: Guest — Title] |
| 2.2 | Source citations | Check cited sources | Citations reference real transcript names and guest names |
| 2.3 | Follow-up question | Ask "Can you elaborate on that?" after 2.1 | Response builds on previous answer, maintains context |
| 2.4 | Unknown topic | Ask "What does Lenny say about quantum physics?" | Response acknowledges the topic isn't covered in the transcripts |
| 2.5 | Specific guest | Ask "What advice does Brian Chesky give?" | Response cites Brian Chesky's transcript specifically |
| 2.6 | Multi-source synthesis | Ask "How do different guests think about growth?" | Response synthesizes insights from multiple transcripts |

## 3. Ship 30 for 30 Essay

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 3.1 | Generate essay | Ask "Write a Ship 30 essay about retention" | ~1,250 word essay with hook, headings, bullets, bold, takeaway |
| 3.2 | Essay in artifact viewer | After 3.1 | Essay appears in the artifact viewer panel (not inline in chat) |
| 3.3 | Essay formatting | Inspect the generated essay | Has ## headings, **bold**, bullet points, clear sections |
| 3.4 | Essay grounding | Check essay content | Claims cite specific transcripts/guests |
| 3.5 | Word count | Count words in the essay | Between 1,000 and 1,500 words |

## 4. Artifact Viewer

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 4.1 | Markdown rendering | Generate a Markdown artifact | Renders with formatted headings, lists, bold text |
| 4.2 | HTML rendering | Ask "Create an HTML summary of our discussion" | HTML renders in sandboxed iframe beside the chat |
| 4.3 | Artifact isolation | Inspect the iframe in browser DevTools | iframe has `sandbox` attribute, no access to parent DOM |
| 4.4 | Copy/Download | Click Copy or Download on an artifact | Content copies to clipboard / downloads as file |
| 4.5 | Artifact toggle | Click to show/hide the artifact panel | Panel opens and closes smoothly |

## 5. LLM Provider Toggle

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 5.1 | Ollama active | Start with LLM_PROVIDER=ollama | UI shows "Ollama:  llama3.2:3b" badge |
| 5.2 | Model in response | Send a message | Response metadata shows model=" llama3.2:3b" |
| 5.3 | Switch to cloud | Change .env to LLM_PROVIDER=anthropic, restart | UI shows "Anthropic: claude-sonnet" badge |
| 5.4 | Health check | Visit /health | Shows current provider status |
| 5.5 | Ollama down | Stop Ollama, send a message | Graceful error message (not crash), health shows degraded |

## 6. Error Handling & Edge Cases

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 6.1 | Empty message | Try to send an empty message | Send button disabled or input validation prevents it |
| 6.2 | Very long message | Send a 5,000+ character message | Accepted and processed (up to 10,000 char limit) |
| 6.3 | Rapid messages | Send 5 messages quickly | All messages processed in order, no duplicates |
| 6.4 | Page refresh during loading | Send a message, refresh while loading | User message persisted, can retry |
| 6.5 | Network error | Disconnect network, send a message | Error shown to user, can retry when reconnected |

## 7. Responsive Design

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 7.1 | Desktop (1440px+) | Open at full width | Chat + artifact viewer side by side |
| 7.2 | Tablet (768px) | Resize browser to 768px | Sidebar collapses, artifact viewer stacks below |
| 7.3 | Mobile (375px) | Resize to 375px | Single column, hamburger menu for sessions |

## 8. Accessibility

| # | Test | Steps | Expected Result |
|---|------|-------|-----------------|
| 8.1 | Keyboard navigation | Tab through the interface | All interactive elements focusable in logical order |
| 8.2 | Screen reader | Use VoiceOver/NVDA on the chat | Messages announced with role (user/assistant) |
| 8.3 | Color contrast | Check with browser contrast tool | All text meets WCAG AA contrast ratio (4.5:1) |
| 8.4 | Focus indicators | Tab through elements | Visible focus ring on all interactive elements |
