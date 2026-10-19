# ComicPile SEO launch runbook (issue #3072)

This runbook covers the launch chores that no autonomous worker can perform. The
code-level public-surface contract lives in
[`docs/SEO_PUBLIC_SURFACE.md`](../SEO_PUBLIC_SURFACE.md); the machine-checkable
part of the launch evidence is produced by
[`frontend/scripts/seo-launch-audit.mjs`](../../frontend/scripts/seo-launch-audit.mjs).

The division of labor is deliberate:

| Step | Who | Evidence |
| --- | --- | --- |
| The public surface is crawlable, indexable, and policy-correct | Factory (code) | Route table, `robots.txt`, sitemap, and their regression tests |
| The deployment actually serves that surface | Factory (tool) + operator (run) | SEO launch audit report |
| Search Console ownership, sitemap submission, index inspection, metrics | Operator | Baseline record in this directory |
| Off-site discovery and outreach | Operator | Baseline record in this directory |

Nothing in this runbook may be marked complete by a worker. A worker can
produce the audit report and validate the record; it cannot verify an account,
submit a sitemap, read a metric, or contact a third party.

## Step 0 — Audit the deployed origin first

Run the audit before touching Search Console. It proves that the deployment
serves the policy the code defines, and it produces the URL checklist used in
step 3.

```bash
pnpm --filter frontend run audit:seo-launch -- --base-url https://comic-pile.vercel.app
```

The audit reads the launch record from `docs/operations/seo-launch-baseline.json`
by default, writes `dogfood-output/seo-launch-audit/seo-launch-audit.md` and
`dogfood-output/seo-launch-audit/seo-launch-audit.json`, and exits non-zero
when it finds a blocking problem. Pass `--baseline <path>` to audit a
different record. It checks that:

- every indexable route serves one stable canonical URL and is not blocked by
  `robots.txt`, a robots meta tag, or an `X-Robots-Tag` header;
- every utility and authenticated route carries an explicit `noindex` directive
  and is disallowed in `robots.txt`;
- the served `robots.txt` advertises the sitemap on the audited origin;
- the served `sitemap.xml` lists exactly the indexable routes and nothing else.

A route that is only disallowed in `robots.txt` is reported as a blocking
problem. `robots.txt` prevents crawling, not indexing: a URL that another site
links to can still be indexed from that link. The `noindex` directive is the
signal that survives that case, and the canonical policy requires both.

If the audit reports indexable private routes, the deployment is not serving
the per-route metadata that the build produces. Issue #3905 tracks the routing
class of that defect; fix it before continuing, because the Search Console
inspection in step 3 would only confirm the wrong thing.

## Step 1 — Verify Google Search Console ownership

1. Add the property `https://comic-pile.vercel.app` to the Search Console
   account that owns the domain. Use a URL-prefix property for the exact
   origin, or a Domain property for the apex and its subdomains.
2. Verify the property. Prefer the **DNS TXT record** method: the record
   survives redeploys and does not depend on anything the application serves.
   The record name and value come from the Search Console property page.
3. Confirm the property is active, then record the verification in
   [`seo-launch-baseline.json`](seo-launch-baseline.json) by setting
   `searchConsole.ownershipVerified` to `true` and `recordedAt` to the
   verification date.

Account access stays with the repository owner. A worker must never be given
Search Console credentials, and ownership must never be asserted without the
property actually being active.

## Step 2 — Submit the production sitemap

1. In Search Console, open **Sitemaps** and submit the sitemap URL that the
   audit confirmed:

   ```text
   https://comic-pile.vercel.app/sitemap.xml
   ```

2. The sitemap must list exactly the indexable public routes. ComicPile has a
   single crawl target, the landing page, so a valid sitemap contains one
   `<loc>` entry. The audit fails with `sitemap-unexpected-url` if a private or
   utility route ever appears there.
3. Wait for the status to become "Success", then set
   `searchConsole.sitemapSubmitted` to `true` in the baseline record.

Submitting the sitemap is a request to Google, not a guarantee of indexing.
The index count in step 4 is the measured outcome.

## Step 3 — Inspect the intended public URLs

Use the audit's Markdown report as the checklist. It lists every route in the
canonical table with its observed status, canonical URL, robots directive, and
`robots.txt` verdict.

1. Run **URL Inspection** on the landing page `https://comic-pile.vercel.app/`.
   Confirm that Google-selected canonical equals the landing page and that the
   page is eligible for indexing.
2. Run **URL Inspection** on the sitemap URL to confirm Google has fetched it.
3. Inspect at least one utility route (`/login`) and one authenticated route
   (`/queue`). Both must report that the page is not indexed. The audit proves
   the response carries `noindex`; the inspection proves Google's view agrees.
4. Record any discrepancy between the audit report and the inspection result
   in the `notes` field of the baseline record, and open an issue for it.

Inspecting private URLs is safe: they are disallowed in `robots.txt`, so the
request does not fetch the page content.

## Step 4 — Record the baseline index and search metrics

Fill the `searchConsole` block of
[`seo-launch-baseline.json`](seo-launch-baseline.json) so later changes are
measurable:

| Field | Meaning | Where it comes from |
| --- | --- | --- |
| `indexedPageCount` | Number of indexed pages for the property | Search Console → Pages → Indexed |
| `impressions` | Search impressions in the reporting window | Search Console → Performance |
| `clicks` | Search clicks in the reporting window | Search Console → Performance |
| `recordedAt` | Date the baseline was taken | The day the numbers were read |

Use the same reporting window every time so the numbers compare. A brand-new
property legitimately reports `0` impressions and `0` clicks; record the zero
rather than leaving the field empty, because an empty field means "not
measured".

Validate the record after editing it:

```bash
pnpm --filter frontend run audit:seo-launch -- --base-url https://comic-pile.vercel.app
```

The report's **Operator steps still open** section lists every field that is
still missing, so the record cannot silently drift back to an empty state.

## Step 5 — Work the off-site discovery opportunities

The baseline record ships with five identified opportunities. They are
candidates, not commitments, and the record's `outreach` field starts at
`not-started`.

Every candidate must pass the relevance test before it is pursued:

> Would a ComicPile reader, a self-hoster, or a personal-software builder
> find the linked page genuinely useful, and would ComicPile be genuinely
> useful to them?

A listing that only exists to place a link fails the test, no matter how
relevant the topic looks.

Hard rules for outreach:

- **Earned links only.** No paid placements, no link exchanges, no sponsored
  posts, no guest posts that exist only for the link.
- **No link farms.** No mass submission to directories, no automated posting,
  no spun or expired domains, no scraped directories, no comment or forum
  link drops.
- **One submission per destination.** A list that rejects the project gets one
  honest attempt, not a campaign.
- **Keep the record truthful.** `outreach` moves through `not-started`,
  `contacted`, `declined`, and `published`. Never record a link that was not
  actually earned, and never claim a placement that was paid for.

Update the `outreach` state and add a short note for each candidate that is
actually pursued, so the record shows what was tried and what happened.

## Evidence checklist

| Acceptance item for #3072 | Where the evidence lives |
| --- | --- |
| Search Console ownership is verified | `searchConsole.ownershipVerified` in the baseline record, after step 1 |
| The production sitemap is submitted | `searchConsole.sitemapSubmitted` in the baseline record, after step 2, plus the sitemap URL the audit confirms |
| Intended public URLs are indexable and private URLs are not | The audit report's URL tables (step 0) and the Search Console inspections (step 3) |
| Baseline indexing and search metrics with a date | `indexedPageCount`, `impressions`, `clicks`, and `recordedAt` in the baseline record (step 4) |
| At least three realistic off-site discovery opportunities | The `offsiteOpportunities` list in the baseline record, validated by the audit |
| Backlink outreach is legitimate and product-relevant | `linkPolicy: "earned-only"`, the per-candidate `paid: false` flag, and the outreach notes (step 5) |
