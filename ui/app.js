const fmt = (value, suffix = "") => value === null || value === undefined ? "Unknown" : `${new Intl.NumberFormat().format(value)}${suffix}`;
const pct = value => value === null || value === undefined ? "Unknown" : `${Number(value).toFixed(1)}%`;
const ms = value => value === null || value === undefined ? "Unknown" : `${Number(value).toFixed(0)} ms`;

function card(label, value) {
  return `<div class="card"><span class="label">${label}</span><strong class="value">${value}</strong></div>`;
}

function render(payload) {
  const session = payload.snapshot.sessions[0];
  const status = document.querySelector("#status");
  if (!session) {
    status.textContent = "No rollout data";
    document.querySelector("#cards").innerHTML = "";
    return;
  }
  status.textContent = "Live · local read-only";
  document.querySelector("#source").textContent = payload.source_file || "";
  document.querySelector("#cards").innerHTML = [
    card("TOTAL TOKENS", fmt(session.total_tokens)),
    card("REQUESTS / TURNS", `${fmt(session.request_count)} / ${fmt(session.turn_count)}`),
    card("INPUT TOKENS", fmt(session.input_tokens)),
    card("CACHED TOKENS", fmt(session.cached_tokens)),
    card("OUTPUT TOKENS", fmt(session.output_tokens)),
    card("CACHE HIT", pct(session.cache_hit_percent)),
    card("TTFT", ms(session.ttft_ms)),
    card("TPS", fmt(session.tps)),
    card("LATENCY", ms(session.latency_ms)),
    card("COST", session.cost_usd === null ? "Unknown" : `$${Number(session.cost_usd).toFixed(4)}`),
  ].join("");

  const distribution = session.distribution || {};
  document.querySelector("#distribution").innerHTML = ["user", "output", "tool_call", "tool_result"].map(key => {
    const item = distribution[key] || {};
    return `<div class="dist"><span class="label">${key.replace("_", " ").toUpperCase()}</span><strong>${fmt(item.tokens)}</strong><span class="quality">${item.quality || "unknown"}</span></div>`;
  }).join("");

  document.querySelector("#turns").innerHTML = payload.snapshot.turns.map(turn => `
    <tr><td>${turn.turn_id}</td><td>${fmt(turn.request_count)}</td><td>${fmt(turn.input_tokens)}</td><td>${fmt(turn.cached_tokens)}</td><td>${fmt(turn.output_tokens)}</td><td>${ms(turn.latency_ms)}</td></tr>
  `).join("");
}

async function refresh() {
  try {
    const response = await fetch(`/api/snapshot?ts=${Date.now()}`, { cache: "no-store" });
    render(await response.json());
  } catch (error) {
    document.querySelector("#status").textContent = "Waiting for monitor";
  }
}

refresh();
setInterval(refresh, 1000);
