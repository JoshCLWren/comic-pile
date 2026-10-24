# Custom CBL Create cycle feedback

An empty Custom CBL can be rejected when the reader's existing constraints already form a cycle.
Create now decodes the same structured cycle response used by Save, displays the named comics,
preserves the attempted name, and explains that no new list was saved. It does not blame an empty
new list for introducing an existing cycle or expose the server's raw Issue-ID diagnostic.

Cycle edges include the owning series IDs from the already loaded reader-scoped snapshot. For
prerequisite edges, the editor offers links to `/thread/:id?prerequisites=1`, which opens the
existing prerequisite dialog after the owned series loads. Closing the dialog does not reopen it
on a background refresh. Older responses without series IDs still show readable feedback without
inventing a destination. Selecting an existing list clears a failed Create's feedback.
The Edit Series Notes label is associated with its textarea so the corrective editing path is
accessible by name.

This changes error presentation and remediation navigation. Cycle validation and transactional
rollback remain in force. It does not delete, classify or repair legacy production prerequisites;
any such operation retains the separate preview and approval gate in issue #1615.

Regressions cover PostgreSQL cycle rollback and owning-series IDs, Create feedback and draft
preservation, existing Save behavior, and desktop/mobile Chromium navigation into the real
prerequisite editor. The browser test supplies only the legacy cycle's 422 response; account,
series, plan creation and editor reads use the real local API.
After dismissal, it saves a real notes edit and verifies the dialog remains closed when refreshed
series data renders.
