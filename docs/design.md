# TokenWatch MVP design

```text
Codex GUI
   │  loopback CDP: current thread UUID
   ▼
SessionIndex ── exact UUID → rollout JSONL
   │
   ▼
IncrementalRolloutReader ── latest token_count snapshot
   │
   ├── fixed-width text renderer
   └── GTK3 + X11 companion window
```

CDP is used only to identify the currently viewed GUI thread. The rollout
reader is read-only and never treats the newest file as a substitute for a
missing thread mapping. If the renderer returns equally strong candidates,
the companion stays hidden.

The JSONL reader replays a selected file once, then remembers its byte offset
and consumes only complete appended lines. File replacement and truncation
reset the selected file safely.

`REQ` is the number of valid `token_count` events in the selected rollout.
Those are the only direct per-request usage snapshots observed in the local
Codex schema. `Session` cache hit is cumulative cached input divided by
cumulative input; `Last` cache hit uses the latest snapshot; `Context` uses
latest input divided by the model context window.

The GTK window is independent from Codex. Under X11, it uses a normal utility
window with GTK's keep-above hint applied once after mapping, so it stays above
all applications without repeated restacking. The initial placement is to the
right of Codex, or inside the upper-right area when Codex is already maximized;
after that first placement, the user's manual position is kept as an absolute
desktop coordinate. Codex movement, resizing, and maximize changes do not
reposition the companion. It only hides when Codex is minimized or unavailable.
