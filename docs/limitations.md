# Known limitations

- The desktop rollout log currently exposes exact aggregate input/cached/output usage per model request, but not a provider-supplied token count for each individual user message, tool call, or tool result.
- User, tool-call, and tool-result distribution buckets are therefore marked `estimated` or `unknown`; they are never presented as exact provider billing counts.
- TTFT requires a first streamed agent-message delta. If the local rollout log contains only completed messages, TTFT is `unknown`.
- TPS requires a reliable generation interval. It is `unknown` when TTFT or completion timing is unavailable.
- Cost is `unknown` unless the caller supplies an explicit model price table. ChatGPT-managed Codex usage is not assumed to be API-billed.
- The App Server's public documentation confirms event names and lifecycle but does not fully specify the nested token-usage payload used by every desktop build.
- The MVP polls the local file for the dashboard. A direct App Server event client is a later extension.
