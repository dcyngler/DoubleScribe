// GET /api/download -- logs a download event (country + referrer, no IP
// storage) to the DOWNLOADS Analytics Engine dataset, then redirects to the
// actual installer. Fronting the static file this way is what makes the
// stats in /api/stats possible.
export async function onRequestGet({ request, env }) {
  const referer = request.headers.get("Referer") || "(direct)";
  const country = request.cf?.country || "XX";

  env.DOWNLOADS?.writeDataPoint({
    blobs: [country, referer],
    doubles: [1],
    indexes: ["download"],
  });

  return Response.redirect(new URL("/downloads/DoubleScribeSetup.exe", request.url), 302);
}
