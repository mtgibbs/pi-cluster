// Build the runner request {agent, event} from the "Run an agent" form (CONTRACT.md §1).
// The form text is DATA: it is only ever placed inside event.data.ask (a JSON string in the
// POST body) — never into a URL, a header, or SQL.
const AGENTS = ['media-investigator'];          // keep in step with the form's dropdown
const MAX_ASK = 8000;                            // whole event must stay well under 64 KiB
const MAX_SUBJECT = 200;

let f = {};
try { f = $('Agent Form').first().json || {}; } catch (e) { f = $input.first().json || {}; }
const pick = (...keys) => { for (const k of keys) if (f[k] !== undefined && f[k] !== null) return f[k]; return ''; };

const agent = String(pick('Agent', 'agent')).trim();
if (!AGENTS.includes(agent)) throw new Error(`Unknown agent "${agent}" (allowed: ${AGENTS.join(', ')})`);

const ask = String(pick('What should it look into?', 'ask')).trim().slice(0, MAX_ASK);
if (!ask) throw new Error('Nothing to look into: the ask is empty');

// subject is required by the contract; default to a neutral one when the form leaves it blank.
const subject = (String(pick('Subject (optional)', 'subject')).replace(/[\r\n\t]+/g, ' ').trim()
  || `manual:${agent}`).slice(0, MAX_SUBJECT);

// ULID-shaped id (Crockford base32: 10 chars of ms time + 16 random). Uniqueness only — not a
// secret, so Math.random is fine (the Code sandbox has no `crypto`). The runner dedupes on
// (event.id, agent), so a fresh id per submission means a fresh run.
const B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
let t = Date.now(), time = '';
for (let i = 0; i < 10; i++) { time = B32[t % 32] + time; t = Math.floor(t / 32); }
let rand = '';
for (let i = 0; i < 16; i++) rand += B32[Math.floor(Math.random() * 32)];
const id = time + rand;

const event = {
  id,
  type: 'manual.investigate',
  source: 'matt',
  subject,
  dedupe_key: id,
  trust: 'internal',
  data: { ask },
};
return [{ json: { agent, event } }];
