// GET /api/stats?token=... -- returns download counts (by day / country /
// referrer) from the DOWNLOADS Analytics Engine dataset, for the stats.html
// dashboard. Gated by STATS_TOKEN so the numbers aren't publicly readable.
// Env (set via `wrangler pages secret put` -- see website/README.md):
//   STATS_TOKEN            -- long random string, checked against ?token=
//   CF_ACCOUNT_ID           -- Cloudflare account ID
//   CF_ANALYTICS_API_TOKEN  -- API token with Account Analytics:Read
const QUERY = `
  SELECT
    toStartOfDay(timestamp) AS day,
    blob1 AS country,
    blob2 AS referer,
    sum(_sample_interval) AS downloads
  FROM double_scribe_downloads
  WHERE timestamp > now() - INTERVAL '90' DAY
  GROUP BY day, country, referer
  ORDER BY day DESC
`;

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export async function onRequestGet({ request, env }) {
  if (!env.STATS_TOKEN || !env.CF_ACCOUNT_ID || !env.CF_ANALYTICS_API_TOKEN) {
    return new Response(
      "Stats aren't configured yet -- STATS_TOKEN / CF_ACCOUNT_ID / CF_ANALYTICS_API_TOKEN missing. See website/README.md.",
      { status: 500 },
    );
  }

  const token = new URL(request.url).searchParams.get("token") || "";
  if (!timingSafeEqual(token, env.STATS_TOKEN)) {
    return new Response("Unauthorized", { status: 401 });
  }

  const res = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${env.CF_ACCOUNT_ID}/analytics_engine/sql`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${env.CF_ANALYTICS_API_TOKEN}` },
      body: QUERY,
    },
  );

  if (!res.ok) {
    return new Response(`Analytics query failed: ${await res.text()}`, { status: 502 });
  }

  const data = await res.json();
  return new Response(JSON.stringify(data), {
    headers: { "content-type": "application/json" },
  });
}
