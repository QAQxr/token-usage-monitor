# Data-source investigation

## Selected MVP source: local rollout JSONL

The active Codex environment writes a rollout file under:

`/home/o_o/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`

The current workspace session was inspected without printing message content. The observed record types include:

- `session_meta`: session id, working directory, provider and model metadata.
- `turn_context`: model and turn context metadata.
- `event_msg.task_started`: turn id and model context window.
- `event_msg.token_count`: cumulative usage, latest-request usage, context window, and rate-limit snapshots.
- `event_msg.item_started` / `event_msg.item_completed`: tool and work-item lifecycle timestamps.
- `response_item.message`: user and assistant messages.
- `response_item.custom_tool_call`: tool invocation metadata.
- `response_item.custom_tool_call_output`: tool result metadata.
- `event_msg.task_complete`: turn completion boundary.

This source is the MVP's concrete adapter because it is already available locally, requires no new credentials, and exposes the fields needed for exact input/cached/output accounting.

## Official App Server source

The official Codex App Server documentation describes a structured streaming interface for rich clients. It documents:

- `thread/tokenUsage/updated` for active-thread usage updates.
- `turn/started` and `turn/completed` for turn lifecycle.
- `item/*` notifications for user messages, agent messages, command execution, MCP tool calls, and other items.
- `account/rateLimits/read` and `account/rateLimits/updated` for quota windows.
- `account/usage/read` for account-level token summaries and daily buckets.

The public documentation names the token-usage event but does not define every nested payload field used by the current desktop rollout logs. The project therefore keeps an App Server-compatible normalized event model while using rollout JSONL as the initial concrete adapter. A direct App Server adapter can be added later without changing the metric layer.

Reference: [Codex App Server documentation](https://learn.chatgpt.com/docs/app-server?translationFallback=zh-Hans).

## Field mapping

| Metric input | Rollout field | Quality |
| --- | --- | --- |
| Input tokens | `payload.info.last_token_usage.input_tokens` | Exact |
| Cached tokens | `payload.info.last_token_usage.cached_input_tokens` | Exact |
| Output tokens | `payload.info.last_token_usage.output_tokens` | Exact |
| Total tokens | `payload.info.last_token_usage.total_tokens` | Exact |
| Context window | `payload.info.model_context_window` | Exact when present |
| Rate limits | `payload.rate_limits` | Exact when present |
| Turn id | `task_started.turn_id` | Exact |
| Tool lifecycle | `item_started` / `item_completed` | Exact for observed items |
| User/assistant text | `response_item.message` | Exact content, token count unavailable |

## Privacy boundary

The MVP retains only normalized metadata in memory. It does not copy, persist, or display message bodies, tool arguments, command output, credentials, or encrypted reasoning content.
