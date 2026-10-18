# ComicPile Public SEO Surface

This document is the durable, code-level contract for ComicPile's crawlable public surface
(epic #3064). It records which routes are indexable, where the policy lives, how it is
regression-tested, and which launch chores are intentionally manual.

## Indexability policy

Exactly one route is a search crawl target: the public landing page at `/`. Every other
route is either a public utility page that must not appear in search results, or an
authenticated route that must never be crawled or indexed.

| Visibility | Meaning | Routes |
|---|---|---|
| `public-indexable` | Crawlable public surface; one stable canonical URL. | `/` |
| `public-noindex` | Public utility or redirect source; never indexed. | `/login`, `/register`, `/forgot-password`, `/reset-password`, `/demo`, `/rate`, `/analytics`, `/roll`, `/help`, `/threads/:id` |
| `private` | Authenticated routes; never crawl targets. | Everything else, including `/queue`, `/thread/:id`, `/creators*`, `/history`, `/sessions/:id`, `/crossovers*`, `/continuity-plans*`, `/cbl-sources`, `/whats-new`, `/glossary`, `/identity-inbox` |

Unknown paths default to `private`, so a newly added route can never become indexable by
accident. New routes must be classified in the canonical table before they are added to
`App.tsx`.

## Sources of truth

The policy is expressed in one place per surface. None of them duplicates another.

- `frontend/src/seo/routeSeo.ts` — the canonical route indexability table and the
  `matchRouteSeo` lookup used by the client `Seo` head manager.
- `frontend/src/seo/Seo.tsx` — applies the table to `document.head` on navigation: one
  canonical link and `index, follow` for indexable routes; `noindex, nofollow` and no
  canonical for everything else.
- `frontend/public/robots.txt` — the version-controlled crawler policy served at
  `/robots.txt`. Only `/` is allowed; every private route family is `Disallow`ed.
- `frontend/scripts/generate-sitemap.mjs` — generates `sitemap.xml` and the built
  `robots.txt` from the canonical table and policy at build time.
- `frontend/scripts/generate-route-html.mjs` — prerenders per-route HTML metadata from the
  same table so crawlers see route-specific title, description, canonical, and robots tags
  without executing JavaScript.
- `app/main.py` — serves the built artifacts and emits `X-Robots-Tag: noindex, nofollow`
  for every SPA path except `/`.

## Automated regression coverage

The policy is enforced across artifacts, so drift fails CI rather than shipping:

- `frontend/src/unit/seoRouteTable.test.ts` — the table's internal contract.
- `frontend/src/unit/seoIndexabilityPolicy.test.ts` — cross-artifact guard: every route in
  `App.tsx` is classified, every classified route exists in `App.tsx`, and every
  non-indexable route is disallowed by `robots.txt` prefix rules.
- `frontend/src/unit/sitemap.test.ts` and `frontend/scripts/generate-sitemap.test.mjs` — the
  sitemap lists exactly the indexable routes and nothing else.
- `frontend/src/unit/seoHtmlGeneration.test.ts` — the prerendered metadata generator.
- `tests/test_seo_crawlability.py` — the served HTTP surface: `X-Robots-Tag` policy,
  `robots.txt` content and cache headers, the sitemap, and the no-JavaScript landing HTML.
- `frontend/src/test/issue-3068-seo-route-cleanup.spec.ts` — browser-level crawlability and
  redirect-chain behavior.

## Manual launch steps

Some launch work cannot be done in code and must not be simulated by automation. These
steps are tracked separately from implementation issues so no factory can claim they
happened (see issue #3072):

1. Verify the production ComicPile origin in Google Search Console.
2. Submit the production `sitemap.xml` after the sitemap and indexability work ships.
3. Inspect the landing page and other intended public URLs for crawl/index status, and
   confirm authenticated URLs are not indexed.
4. Record the baseline indexed-page count and search impressions/clicks with the date.
5. Identify realistic, product-relevant off-site discovery opportunities and pursue only
   legitimate, earned links.

Automated work stops at producing the crawlable, policy-correct surface and its regression
coverage. It does not verify Search Console ownership, submit sitemaps, or earn backlinks.
