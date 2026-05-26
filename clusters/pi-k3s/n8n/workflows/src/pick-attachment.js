// Pick the first SAFE attachment to extract: PDF only, <= 10MB. Everything else
// (docx, images, archives, executables, oversized) is skipped → body fallback.
const atts = ((($('Inbound Mail Webhook').first().json.body) || {}).attachments) || [];
const MAX = 10 * 1024 * 1024;
const pick = atts.find(a => a && a.mimeType === 'application/pdf' && Number(a.size || 0) > 0 && Number(a.size || 0) <= MAX);
return [{ json: { r2Key: pick ? pick.r2Key : '', att_filename: pick ? (pick.filename || 'attachment.pdf') : '', has_att: !!pick } }];
