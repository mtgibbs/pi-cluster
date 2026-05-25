// Read the email straight from the webhook node (so an upstream Ensure-Table node
// in the chain doesn't clobber our input).
const b = ($('Inbound Mail Webhook').first().json.body) || {};
const sys = `You are an extraction service that pulls actionable items from an inbound message for the Gibbs family (kids: ronin, rory). The message may be a school notice, community flyer, bill, event, or general info. Output ONLY a JSON array (no markdown, no commentary). Each item: {"type":"date|dues|assignment|event|site-pointer|info","title":string,"dueAt":ISO-8601 date or datetime or null,"student":"ronin|rory|both|unknown","actionRequired":boolean,"amount":string|null,"teacher":string|null,"class":string|null,"source_hint":short verbatim quote,"confidence":0..1}. Resolve relative dates against the email date. If nothing actionable, return [].`;
const text = String(b.text || '').slice(0, 6000);
const user = `EMAIL DATE: ${b.date || ''}\nFROM: ${b.from || ''}\nSUBJECT: ${b.subject || ''}\nTO: ${b.envelopeTo || ''}\n\nBODY:\n${text}`;
return [{ json: { model: 'qwen3-30b-instruct', temperature: 0.1, max_tokens: 1500, messages: [ { role: 'system', content: sys }, { role: 'user', content: user } ] } }];
