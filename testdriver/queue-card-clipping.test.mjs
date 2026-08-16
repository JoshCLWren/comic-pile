import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { TestDriver } from "testdriverai/vitest/hooks";

/**
 * Regression coverage for issue #1295 (E2E: "keeps mobile cards clipped while
 * exposing actions through the shared overlay") / product issue #625.
 *
 * PRODUCT BEHAVIOR UNDER TEST
 * ---------------------------
 * A queue thread card (`.queue-thread-card`) must CLIP its own content
 * (`overflow: hidden`) so a mobile card stays visually "clipped", while the
 * thread-actions menu escapes the clipped card through the shared overlay
 * portal. The upstream Playwright spec
 * (frontend/src/test/queue-interaction-containment.spec.ts) asserts:
 *
 *     getComputedStyle(card).overflow === "hidden"
 *
 * BUG (#1295): there is NO CSS rule setting `overflow` on `.queue-thread-card`
 * (neither the `.queue-thread-card` class nor the shared `.glass-card` rule in
 * frontend/src/styles.css sets it), so the computed value is "visible" and the
 * assertion times out — the exact failure reported in the issue
 * (Expected "hidden", Received "visible").
 *
 * FIX: give the card `overflow: hidden` (e.g. a `.queue-thread-card { overflow:
 * hidden }` rule in frontend/src/styles.css, or the `overflow-hidden` Tailwind
 * utility on the card element in QueueThreadCard.tsx).
 *
 * HOW THIS TEST PROVES IT
 * -----------------------
 * This test is self-contained and needs no backend, auth, or public tunnel. It
 * ships the harness (testdriver-harness/queue-card-clipping.inline.html) INTO
 * the TestDriver sandbox, serves it on localhost there, and drives it in a real
 * Chrome. The harness renders the exact card DOM from QueueThreadCard.tsx with
 * the real compiled application CSS, plus a toggle that applies the fix. It:
 *   1. shows the card computes overflow "visible" (the bug) with an oversized
 *      "OVERFLOW PROBE" banner spilling below the card, then
 *   2. after the fix is applied, shows the card computes overflow "hidden" and
 *      the probe is clipped by the card box (the corrected behavior).
 */

const __dirname = dirname(fileURLToPath(import.meta.url));
const HARNESS_PATH = resolve(
  __dirname,
  "../testdriver-harness/queue-card-clipping.inline.html",
);
const HARNESS_B64 = readFileSync(HARNESS_PATH).toString("base64");
const PORT = 8752;

describe("Queue interaction containment (#1295 / #625)", () => {
  it("clips the mobile card content once the overflow fix is applied", async (context) => {
    const testdriver = TestDriver(context);

    // Ship the self-contained harness into the sandbox and serve it locally, so
    // the test has zero external dependencies (no backend, auth, or tunnel).
    await testdriver.exec(
      "sh",
      `mkdir -p /tmp/qc && printf '%s' '${HARNESS_B64}' | base64 -d > /tmp/qc/index.html`,
      15000,
    );
    await testdriver.exec(
      "sh",
      `pkill -f 'http.server ${PORT}' 2>/dev/null; nohup python3 -m http.server ${PORT} --directory /tmp/qc > /tmp/qc/server.log 2>&1 & sleep 2; echo served`,
      15000,
    );

    await testdriver.provision.chrome({
      url: `http://localhost:${PORT}/index.html`,
    });

    // The card renders with the same classes as QueueThreadCard.tsx.
    const card = await testdriver.find('the "Sample Thread" queue card');
    expect(card.found()).toBeTruthy();

    // BEFORE the fix: the oversized striped "OVERFLOW PROBE" banner spills past
    // the bottom of the card and the readout reads "computed overflow: visible".
    const bugVisible = await testdriver.assert(
      'the "computed overflow:" readout shows the word "visible" and the striped ' +
        "OVERFLOW PROBE banner spills past the bottom edge of the card",
    );
    expect(bugVisible).toBeTruthy();

    // Apply the product fix (adds overflow: hidden to the card).
    await testdriver.find('the "Apply overflow:hidden fix" button').click();
    await testdriver.wait(1000);

    // AFTER the fix: the readout reads "hidden" and the probe is clipped by the
    // card box — the corrected behavior #1295 requires.
    const clipped = await testdriver.assert(
      'the "computed overflow:" readout shows the word "hidden" and the striped ' +
        "OVERFLOW PROBE banner is now clipped by the card so it no longer spills " +
        "below the card's bottom edge",
    );
    expect(clipped).toBeTruthy();
  });
});
