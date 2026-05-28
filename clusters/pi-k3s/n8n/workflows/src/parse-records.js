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
// stable per-EMAIL identity (msgId) — feeds the deterministic item_key computed
// below, the SINGLE SOURCE OF TRUTH the Store node upserts on. So re-processing/
// retries update rows in place (stable ids) rather than duplicating or re-minting.
const source_msg_id = String(src.messageId || `${src.from || ''}|${src.subject || ''}|${src.date || ''}`);
// normalized title slug: lowercase, non-alphanumerics → '-', collapsed, first ~40 chars.
const slugify = (t) => String(t || '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '')
  .slice(0, 40);
return arr.map(r => {
  const type = r.type || 'info';
  const title = r.title || '';
  const due_at = r.dueAt || null;
  const student = r.student || 'unknown';
  const amount = r.amount || null;
  const course = r.class || null;
  // due_date = YYYY-MM-DD of due_at, '' when null (matches docs/feed all-day contract:
  // take the date portion verbatim, no TZ conversion).
  const due_date = due_at ? String(due_at).slice(0, 10) : '';
  // plain TEXT composite — no md5, no crypto. slug included for ALL items so two
  // distinct same-day items (same type|student|due_date) don't collapse.
  const item_key = [source_msg_id, type, student, due_date, amount || '', course || '', slugify(title)].join('|');
  return { json: {
    source_msg_id,
    type,
    title,
    due_at,
    student,
    action_required: r.actionRequired === true,
    amount,
    teacher: r.teacher || null,
    course,
    source_hint: r.source_hint || null,
    confidence: (typeof r.confidence === 'number' ? r.confidence : null),
    source_channel: src.envelopeTo || '',
    source_subject: src.subject || '',
    source_from: src.from || '',
    original_from: (r.originalFrom && r.originalFrom !== 'null' && r.originalFrom !== 'None') ? r.originalFrom : null,
    item_key
  } };
});
