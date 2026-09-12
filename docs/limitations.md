# Known limitations

- The desktop rollout log currently exposes exact aggregate input/cached/output usage per model request, but not a provider-supplied token count for each individual user message, tool call, or tool result.
- User, tool-call, and tool-result distribution buckets are therefore marked `estimated` or `unknown`; they are never presented as exact provider billing counts.
- TTFT requires a first streamed agent-message delta. If the local rollout log contains only completed messages, TTFT is `unknown`.
- TPS requires a reliable generation interval. It is `unknown` when TTFT or completion timing is unavailable.
- Cost is `unknown` unless the caller supplies an explicit model price table. ChatGPT-managed Codex usage is not assumed to be API-billed.
- The App Server's public documentation confirms event names and lifecycle but does not fully specify the nested token-usage payload used by every desktop build.
- The MVP polls the local file for the dashboard. A direct App Server event client is a later extension.
- The PySide6 desktop window also polls the newest rollout file. “Active” means the file was modified within the configured two-minute freshness window; it is a practical local signal, not an authoritative App Server session state.
- PySide6 is optional and was not installed in the development environment during this phase. The refresh/controller and formatting tests run without Qt; live widget smoke testing requires a local GUI-capable Qt installation.
- The Context card displays aggregate observed tokens against the model context-window value when available. It does not claim that the aggregate Session total is the exact current prompt context after multiple requests.
