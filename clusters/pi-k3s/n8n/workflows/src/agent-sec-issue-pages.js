// One item per page of the plans repo's issues (all states, oldest first, 100 per page). `List Issues` fetches
// each with the github-plans credential; Decide reads every page and refuses to CREATE anything unless the
// listing is complete (a short page reached) and every page answered 200 — a partial view would mean
// duplicate issues. 5 pages = 500 issues; past that, Decide reports "lookup incomplete" and files nothing new.
const PAGES = 5;
const repo = $('Plan Items').first().json.plans_repo;
if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/.test(String(repo))) throw new Error('bad plans repo');
return Array.from({ length: PAGES }, (_, i) => ({ json: {
  page: i + 1,
  url: `https://api.github.com/repos/${repo}/issues?state=all&per_page=100&sort=created&direction=asc&page=${i + 1}`,
} }));
