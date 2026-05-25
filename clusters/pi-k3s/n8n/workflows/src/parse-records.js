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
const src = ($('Inbound Mail Webhook').first().json.body) || {};
// stable per-EMAIL identity (msgId) — the "Delete Prior" node clears this email's
// old rows before insert, so re-processing/retries replace rather than duplicate.
const source_msg_id = String(src.messageId || `${src.from || ''}|${src.subject || ''}|${src.date || ''}`);
return arr.map(r => ({ json: {
  source_msg_id,
  type: r.type || 'info',
  title: r.title || '',
  due_at: r.dueAt || null,
  student: r.student || 'unknown',
  action_required: r.actionRequired === true,
  amount: r.amount || null,
  teacher: r.teacher || null,
  course: r.class || null,
  source_hint: r.source_hint || null,
  confidence: (typeof r.confidence === 'number' ? r.confidence : null),
  source_channel: src.envelopeTo || '',
  source_subject: src.subject || '',
  source_from: src.from || ''
} }));
