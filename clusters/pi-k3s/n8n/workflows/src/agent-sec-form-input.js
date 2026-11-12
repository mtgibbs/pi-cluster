// sec-researcher trigger 3/3: Matt's form (LAN only, https://n8n.lab.mtgibbs.dev/form/agent-sec-run). The text is
// DATA: it only ever lands in event.data.ask (a JSON POST body). Each submission is its own run (fresh key).
const MAX_ASK = 4000;
let f = {};
try { f = $('Sec Form').first().json || {}; } catch (e) { f = $input.first().json || {}; }
const ask = String(f['What should it focus on? (optional)'] || f.ask || '').trim().slice(0, MAX_ASK);

const B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
let t = Date.now(), time = '';
for (let i = 0; i < 10; i++) { time = B32[t % 32] + time; t = Math.floor(t / 32); }
let rand = '';
for (let i = 0; i < 16; i++) rand += B32[Math.floor(Math.random() * 32)];
const key = time + rand;

return [{ json: {
  trigger: 'manual',
  ask: ask || 'General access-control review of clusters/pi-k3s/. Start with what faces the outside.',
  dedupe_key: `sec-researcher:manual:${key}`,
  subject: 'manual',
  cooldown_hours: 1,
} }];
