# Current limitations

- The Codex GUI must be launched with a loopback DevTools endpoint on port
  9222. A user-level launcher is provided in `scripts/chatgpt-tokenwatch`;
  the system application file itself is not modified by the project.
- The exact renderer state used for the current thread is an implementation
  detail of the local Codex GUI, not a public contract. The probe therefore
  ranks several observable candidates and refuses ambiguous results.
- X11 attachment is implemented for the user's Ubuntu X11/XWayland setup;
  Wayland-native window management is outside this MVP. The companion is a
  global always-on-top utility window by explicit design.
- `REQ` counts valid `token_count` snapshots, which is the observable local
  per-request event. It is not inferred from tool-call count or JSONL line
  count.
- Rate limits are displayed as the source's `used_percent` values for the
  primary and secondary windows.
