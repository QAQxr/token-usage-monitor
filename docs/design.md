# MVP design

## Goals

1. Read-only collection from an existing Codex data source.
2. Correct exact accounting where the source provides usage fields.
3. Explicit quality states for estimated or unavailable metrics.
4. Turn and Session aggregation with one reusable metric engine.
5. A compact local UI that can be replaced without changing collection.

## Layers

```text
rollout JSONL / App Server events
             |
             v
       normalized events
             |
             v
       MetricsStore
       /          \
   Turn metrics   Session metrics
             |
             v
       CLI / HTTP JSON / dashboard
```

### Raw source layer

`tokenwatch.sources.jsonl.RolloutJsonlSource` reads complete files or appended lines. It normalizes only metadata needed by the metrics engine and ignores sensitive content.

### Metrics layer

`MetricsStore` consumes normalized events. It deduplicates by source sequence, maintains Turn state, and derives Session totals from Turn state. It never reads files directly.

### Quality model

Every distribution bucket carries a quality label:

- `exact`: supplied by the provider usage payload.
- `estimated`: derived from visible text using a documented heuristic.
- `unknown`: the source does not expose a reliable value.

### UI layer

The local dashboard polls a loopback-only JSON endpoint. The endpoint creates a fresh store from the newest rollout file for each request, keeping the UI stateless and making file rotation safe. A future App Server client can replace the source without changing the HTML.

## Metrics

- `Total Tokens`: sum of exact per-request total tokens.
- `Request Count`: number of unique token-usage events.
- `Turn Count`: observed `task_started` boundaries.
- `Input`, `Cached`, `Output`: sums of exact latest-request usage.
- `Cache Hit %`: cached input divided by input, when input is nonzero.
- `Latency`: turn start to turn completion when both boundaries exist.
- `TTFT`: first observed agent-message delta minus turn start; otherwise `unknown`.
- `TPS`: output tokens divided by generation duration when TTFT and completion timestamps exist; otherwise `unknown`.
- `Cost`: calculated only when an explicit price table is supplied; no price is guessed.

## First commit boundary

The initial commit contains this design and source investigation. Subsequent commits will separate the data model/source, metric engine/tests, and UI.
