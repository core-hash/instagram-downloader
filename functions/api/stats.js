// Pages Function — counter for total downloads.
// Real count lives in KV. Display count = real + passive growth (7/hour).
// GET  /api/stats  → { count }
// POST /api/stats  → increments real count and returns { count }

const KEY = 'downloads';

// Passive growth — counter ticks up over time so it feels alive.
const BASELINE_ISO = '2026-05-09T00:00:00Z';
const PER_HOUR = 7;

function inflate(real) {
  const baseline = Date.parse(BASELINE_ISO);
  const hoursPassed = Math.max(0, (Date.now() - baseline) / 3600000);
  return real + Math.floor(hoursPassed * PER_HOUR);
}

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type',
};

export async function onRequestOptions() {
  return new Response(null, { headers: corsHeaders });
}

export async function onRequestGet({ env }) {
  const raw = await env.MUSE_STATS.get(KEY);
  const real = parseInt(raw || '0', 10);
  return new Response(JSON.stringify({ count: inflate(real) }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store', ...corsHeaders },
  });
}

export async function onRequestPost({ env, request }) {
  const cf = request.cf || {};
  if (cf.botManagement?.score && cf.botManagement.score < 5) {
    const raw = await env.MUSE_STATS.get(KEY);
    return new Response(JSON.stringify({ count: inflate(parseInt(raw || '0', 10)) }), {
      headers: { 'content-type': 'application/json', ...corsHeaders },
    });
  }

  const raw = await env.MUSE_STATS.get(KEY);
  const next = parseInt(raw || '0', 10) + 1;
  await env.MUSE_STATS.put(KEY, String(next));
  return new Response(JSON.stringify({ count: inflate(next) }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store', ...corsHeaders },
  });
}
