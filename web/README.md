# Browser demo (`web/`)

`web/index.html` is a **self-contained, single-file** version of the Design Thinking
Command Center that runs the entire lifecycle **client-side** — no server, no API key.
It mirrors the demo-mode output of the real FastAPI dashboard
(`src/edt_platform/api/dashboard.html`): the same five-phase pipeline, artifacts,
live event stream, run history (saved in your browser via `localStorage`), compare,
and Markdown/JSON/PDF export.

## Open it

- **Locally:** just open `web/index.html` in any browser (double-click, or
  `python -m http.server -d web` then visit `http://localhost:8000`).
- **Hosted on GitHub Pages:** the [`pages`](../.github/workflows/pages.yml) workflow
  publishes this folder. One-time setup: repo **Settings → Pages → Source: GitHub
  Actions**. After a push to the default branch it's served at
  `https://<owner>.github.io/<repo>/`.

## What it is (and isn't)

- ✅ A faithful, interactive preview of the dashboard UX and the Discover → Define →
  Ideate → Prototype → Validate flow, with realistic artifact counts and content.
- ⚠️ The pipeline here is a **browser-side simulation** for demonstration. The real
  agents (Anthropic Claude, Supervisor orchestration, memory/RAG/tools, persistence,
  native PDF) run in the Python backend — launch that with `make dashboard`
  (see the root [README](../README.md)).
