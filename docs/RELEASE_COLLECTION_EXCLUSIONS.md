# Collection exclusions at release-sync boundaries

Release sync checks owner-scoped collection exclusions before adopting a released
Issue and again before extending a followed source's existing membership. An
excluded external ComicVine volume, Thread or Issue is never reintroduced by a
retry. ComicVine numeric and `4050-` volume identifiers are equivalent; titles and
list-local skips do not infer collection decisions.

A confirmed release source supplies stable volume and target Thread identity.
Before adoption, the service checks both the provider-identity reuse path and the
existing Thread/issue-number target the shared adoption primitive would reuse.
This prevents an excluded local Issue from acquiring a new mapping as a side effect.

The API run report adds these counters:

- `excluded_sources`: enabled sources skipped because their volume or Thread is excluded.
- `excluded_issues`: released roster entries skipped because their local target is excluded.
- `skipped_sources`: sources that became unavailable/disabled during provider I/O,
  including excluded sources.

Skipped sources retain their enabled/disabled Follow decision and do not advance
`last_synced_at`. Future and unknown-date counts retain the existing store-date
gate. Aggregate logs contain the same exclusion counters without reader prose.

The mutating boundary acquires the reader lock shared with exclusion writes,
then locks the target Thread and reloads source state after the provider fetch.
Changed targets/volumes fail closed for retry. Deletion or disabling during fetch
cannot resurrect a stale subscription. Both direct extension and sync validate
reader ownership; sibling subscriptions are restricted to the same reader.

Extension flushes within the caller's transaction and never commits internally.
This keeps the exclusion lock held across adoption and extension and lets a caller
roll both back together. API callers continue to commit the completed sync run.

This is #3671's guard on existing release tracking, not an Option E activation or
new scheduler. It does not infer list modes, add workers, create exclusions or
extend the retiring compiler. The existing transitional extension remains in force
until the separately reviewed Reading List cutover.
