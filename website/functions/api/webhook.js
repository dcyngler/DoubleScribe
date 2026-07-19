// POST /api/webhook -- Stripe webhook endpoint. Register this URL
// (https://doublescribe.app/api/webhook) in the Stripe Dashboard for the
// checkout.session.completed event and copy the signing secret into
// STRIPE_WEBHOOK_SECRET (see website/README.md).
import Stripe from "stripe";

export async function onRequestPost({ request, env }) {
  if (!env.STRIPE_SECRET_KEY || !env.STRIPE_WEBHOOK_SECRET) {
    return new Response(
      "Webhook isn't configured yet -- STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET missing. See website/README.md.",
      { status: 500 },
    );
  }

  const stripe = new Stripe(env.STRIPE_SECRET_KEY, {
    httpClient: Stripe.createFetchHttpClient(),
  });

  const signature = request.headers.get("stripe-signature");
  const payload = await request.text();

  let event;
  try {
    event = await stripe.webhooks.constructEventAsync(
      payload,
      signature,
      env.STRIPE_WEBHOOK_SECRET,
    );
  } catch (err) {
    return new Response(`Webhook signature verification failed: ${err.message}`, { status: 400 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object;
    console.log("Donation received", {
      sessionId: session.id,
      amountTotal: session.amount_total,
      currency: session.currency,
      customerEmail: session.customer_details?.email,
    });
  }

  return new Response(JSON.stringify({ received: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
