const resp = $input.first().json;
let content = (((resp.choices || [])[0] || {}).message || {}).content || '';
content = content.replace(/```json/gi, '').replace(/```/g, '').trim();
const s = content.indexOf('['), e = content.lastIndexOf(']');
let arr = [];
if (s >= 0 && e > s) {
  try { arr = JSON.parse(content.slice(s, e + 1)); }
  catch (err) { arr = [{ type: 'info', title: 'PARSE_ERROR', source_hint: content.slice(0, 300), confidence: 0 }]; }
}
if (!Array.isArray(arr)) arr = [];
// stamp source metadata from the original webhook item onto every record
const src = ($('Inbound Mail Webhook').first().json.body) || {};
return arr.map(r => ({ json: Object.assign({}, r, {
  source_channel: src.envelopeTo || '',
  source_subject: src.subject || '',
  source_from: src.from || ''
}) }));
