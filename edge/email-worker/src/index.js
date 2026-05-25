import PostalMime from "postal-mime";

// Cloudflare Email Worker.
// Flow: parse RFC822 -> offload each attachment to R2 -> POST refs-only JSON to n8n.
// On any failure we THROW, so Cloudflare temp-rejects and the sending server retries
// (no mail lost while n8n is down). Orphaned R2 objects from a retry are cleaned up by
// the bucket's 48h lifecycle rule.
export default {
  async email(message, env) {
    const rawBuf = await new Response(message.raw).arrayBuffer();
    const parsed = await PostalMime.parse(rawBuf);

    // Offload attachments to R2; keep only references in the payload (never bytes).
    const attachments = [];
    for (const att of parsed.attachments ?? []) {
      const safeName = (att.filename ?? "file").replace(/[^\w.\-]+/g, "_");
      const key = `inbound/${crypto.randomUUID()}/${safeName}`;
      const bytes = att.content; // ArrayBuffer
      await env.BUCKET.put(key, bytes, {
        httpMetadata: { contentType: att.mimeType ?? "application/octet-stream" },
      });
      attachments.push({
        filename: att.filename ?? "",
        mimeType: att.mimeType ?? "",
        size: bytes?.byteLength ?? 0,
        r2Key: key,
      });
    }

    const payload = {
      // envelope (message.*) is the authoritative sender/recipient; parsed.* is the header view
      envelopeFrom: message.from,
      envelopeTo: message.to,
      from: parsed.from?.address ?? message.from,
      fromName: parsed.from?.name ?? "",
      subject: parsed.subject ?? "",
      text: parsed.text ?? "",
      html: parsed.html ?? "",
      messageId: parsed.messageId ?? "",
      date: parsed.date ?? "",
      attachments, // references only
    };

    const res = await fetch(env.N8N_WEBHOOK_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-auth-token": env.N8N_TOKEN,
      },
      body: JSON.stringify(payload),
    });

    // Throw on failure -> Cloudflare temp-rejects -> sender retries -> no mail lost.
    if (!res.ok) {
      throw new Error(`n8n webhook returned ${res.status} ${res.statusText}`);
    }
  },
};
