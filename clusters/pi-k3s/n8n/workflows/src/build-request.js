const b = ($('Inbound Mail Webhook').first().json.body) || {};
// attachment text comes from "Extract from File" (runs with continueOnError; empty if no PDF)
let attText = '';
try { const e = $('Extract from File').first().json || {}; attText = String(e.text || e.data || e.extractedText || ''); } catch (err) {}
attText = attText.slice(0, 6000);
let fn = '';
try { fn = (($('Pick Attachment').first().json) || {}).att_filename || ''; } catch (err) {}
const sys = `You are an extraction service that pulls actionable items from an inbound message for the Gibbs family (kids: ronin, rory). The message may be a school notice, community flyer, bill, event, or general info, and may include an attached PDF. Output ONLY a JSON array (no markdown). Each item: {"type":"date|dues|assignment|event|site-pointer|info","title":string,"dueAt":ISO-8601 date or datetime or null,"student":"ronin|rory|both|unknown","actionRequired":boolean,"amount":string|null,"teacher":string|null,"class":string|null,"source_hint":short verbatim quote,"confidence":0..1,"originalFrom":string|null}. Resolve relative dates against the email date. If the body shows the email was forwarded (e.g. a "From:" header inside a quoted block), set originalFrom to that sender's email address; otherwise null. If nothing actionable, return [].`;
const bodyText = String(b.text || '').slice(0, 5000);
let user = `EMAIL DATE: ${b.date || ''}\nFROM: ${b.from || ''}\nSUBJECT: ${b.subject || ''}\nTO: ${b.envelopeTo || ''}\n\nBODY:\n${bodyText}`;
if (attText.trim()) user += `\n\n--- ATTACHED PDF (${fn}) ---\n${attText}`;
return [{ json: { model: 'qwen3-30b-instruct', temperature: 0.1, max_tokens: 1500, messages: [ { role: 'system', content: sys }, { role: 'user', content: user } ] } }];
