---
name: gemini-3x-models-are-real
description: The gemini-3.x model IDs in this project are real, not placeholders
metadata:
  type: project
---

The Gemini model IDs in CLAUDE.md / the LLM router (`gemini-3.1-pro-preview`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`) are **real, current models** in the user's environment — do NOT treat them as fictional placeholders.

**Why:** They postdate my training cutoff (2026-01), so I wrongly "corrected" them to gemini-2.5-* once; the user confirmed gemini-3.1-pro-preview exists and told me to use it. The project date is mid-2026.

**How to apply:** Keep the gemini-3.x IDs as the router defaults (`services/engine/llm/router.py` DEFAULT_MODELS) and in `.env.example` / CLAUDE.md §3. Don't downgrade them.
