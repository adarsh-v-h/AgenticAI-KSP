# FourToFive — Step 5 of 5 (Final Step)

> **Status update (June 19, 2026):** Two of the three Step 5 features are shipped and tested:
> - ✅ **Network graph** — `network_builder.py` + `GET /api/graph/fir/{id}` & `/accused/{id}` + lazy-loaded `NetworkGraph.jsx` (vis-network). See `Docs.md` §10.7.
> - ✅ **Voice pipeline** — `zia_voice.py` + `POST /api/voice/transcribe` & `/speak` + `VoiceInput.jsx` (mic) + on-demand "Read aloud". See `Docs.md` §10.8.
>
> **Remaining: the Media Viewer (below).** This is the last piece. Read `Docs.md` before touching any file — it documents the actual shipped code.

---

## Remaining Feature — Media Viewer

### Goal

The backend already resolves evidence media for any result rows that carry a `fir_id` (`pipeline/media_resolver.py` → `resolve_media()`), but it emits **placeholder URLs** (`/api/media/{stratus_file_id}`) and the frontend only renders a flat text list of attachments (`MessageBubble.jsx` → `.media-list`). Nothing is actually viewable.

This step makes evidence **viewable**: images open in a lightbox, audio/video play inline, documents open in a new tab.

### Demo-safe scope decision (confirmed)

The seed data uses **placeholder Stratus IDs**, not real uploaded files — so generating real signed URLs would 404. Per the agreed plan we take the **honest, low-compute path**:

- **Do NOT** wire real Stratus signing or upload demo files.
- Keep `resolve_media()` returning the existing placeholder-style URL, but make it explicit: return a URL that begins with `/api/media/unavailable` so the frontend can detect it.
- The `MediaViewer` renders a clean **"preview unavailable in demo environment"** card for unavailable media instead of a broken `<img>`/`<audio>`/`<video>`. For any real/served URL (future-proofing) it renders the actual media.

This looks intentional, not broken, and adds essentially zero compute. Real Stratus signing is documented as post-hackathon backlog.

---

### Implementation Plan

#### Backend — `pipeline/media_resolver.py` (small change)

One change: make the placeholder URL self-describing so the frontend can branch on it. In `resolve_media()`, change the emitted url from:

```python
"url": f"/api/media/{r.get('stratus_file_id')}",
```

to a clearly-unavailable form that still carries the file id and name:

```python
"url": f"/api/media/unavailable?file={r.get('stratus_file_id')}",
```

Everything else (the single parameterized query, `collect_fir_ids`, the returned dict shape) stays the same. No new backend endpoint, no Stratus call, no new dependency.

> Rationale: the existing `/api/media/{id}` route doesn't exist as a real handler, so the current placeholder is already non-functional. Making it explicitly `unavailable` lets the UI render a clean state instead of a broken tag — same compute, better UX.

#### Frontend — `components/MediaViewer.jsx` (new)

Renders an array of attachments (`[{media_type, url, description, fir_id}]`):

- **`url` starts with `/api/media/unavailable`** → neutral placeholder card (icon + filename + "Preview unavailable"). Never renders a broken media tag.
- **image** → small thumbnail; click opens a lightbox overlay (dark backdrop, centered image, close on backdrop/✕).
- **audio** → `<audio controls>` with the description as a label.
- **video** → `<video controls>` (capped width) with the description label.
- **document / other** → "View document" link opening `url` in a new tab.

State: a single `lightboxUrl` (null = closed). No external deps — plain browser `<img>/<audio>/<video>`.

#### Frontend — `components/MessageBubble.jsx` (small change)

Replace the existing inline `.media-list` block (the flat `<ul>` of pills) with `<MediaViewer attachments={mediaAttachments} />`. Keep the existing `mediaAttachments` prop and the `Array.isArray(...) && length > 0` guard.

#### Frontend — `styles/main.css` (additions)

`.media-viewer` (flex wrap), `.media-thumb` (80px, object-fit cover, pointer), `.media-placeholder-card` (dashed border, icon + text), `.lightbox-overlay` (fixed, dark backdrop, centered), `.lightbox-image`, `.lightbox-close`. Reuse existing CSS variables (`--hairline`, `--r-md`, `--text-tertiary`, etc.) to stay on-theme.

---

### What "Done" Looks Like

- [ ] `resolve_media()` emits an explicit `/api/media/unavailable?file=...` URL for placeholder evidence
- [ ] `MediaViewer.jsx` renders a clean "preview unavailable" card for unavailable media (no broken tags)
- [ ] Real/served image URLs open in a lightbox; audio/video play inline; documents open in a new tab
- [ ] `MessageBubble.jsx` uses `MediaViewer` instead of the flat attachment list
- [ ] Asking "Show me FIRs that have photo evidence" renders attachment cards cleanly
- [ ] Backend tests cover the `resolve_media()` URL shape; frontend build passes

---

### Tests

- **Backend:** extend `backend/tests/` with a test that `resolve_media()` returns the `/api/media/unavailable` URL form and the expected dict keys (monkeypatch `execute_query`, no DB).
- **Frontend:** `MediaViewer` branch logic (unavailable card vs. image vs. audio/video vs. doc) is simple enough to verify via the production build + a manual smoke test; add a unit test only if a fast harness already exists.

---

### What Is NOT in Step 5 (post-hackathon backlog)

- Real uploaded evidence files in Stratus + real signed URL generation (`storage/stratus.py`) — deferred; demo uses the "preview unavailable" card.
- TTS playback auto-wired to every assistant message (current: on-demand "Read aloud" button).
- Generic file/image attach upload in the composer — report analysis already exists as `POST /api/reports/analyze`.
- Graph community detection / clustering visuals — current graph is a direct relationship dump, sufficient for the demo.

---

## This Is the Last Step

After the Media Viewer ships, every feature from the original scope is implemented or consciously deferred with a documented reason: NL2SQL chat with streaming, multi-turn context, persistent history with PDF export, security-hardened session ownership, network graph visualization, voice input + read-aloud, and media viewing — all on Catalyst.
