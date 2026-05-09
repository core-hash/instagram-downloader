// Pages Function — counter for total downloads.
// GET  /api/stats  → { count }
// POST /api/stats  → increments and returns { count }

const KEY = 'downloads';

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
  const count = parseInt(raw || '0', 10);
  return new Response(JSON.stringify({ count }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store', ...corsHeaders },
  });
}

export async function onRequestPost({ env, request }) {
  // Lightweight abuse mitigation: Cloudflare auto rate-limits, plus we cap +1 per request.
  const cf = request.cf || {};
  if (cf.botManagement?.score && cf.botManagement.score < 5) {
    const raw = await env.MUSE_STATS.get(KEY);
    return new Response(JSON.stringify({ count: parseInt(raw || '0', 10) }), {
      headers: { 'content-type': 'application/json', ...corsHeaders },
    });
  }

  const raw = await env.MUSE_STATS.get(KEY);
  const next = parseInt(raw || '0', 10) + 1;
  await env.MUSE_STATS.put(KEY, String(next));
  return new Response(JSON.stringify({ count: next }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store', ...corsHeaders },
  });
}
