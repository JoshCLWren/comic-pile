import { describe, expect, it } from "vitest";
import { TestDriver } from "testdriverai/vitest/hooks";

// Reproduces / verifies issue #1386 "tons of console spam".
//
// The report shows the production app at https://comic-pile.vercel.app/ logging:
//   - "API Error: AxiosError: Request failed with status code 503"
//   - "ComicPile resume validation failed (attempt 1) ..."
// These come from src/services/api.ts (the axios error interceptor) and
// src/components/ResumeRecovery.tsx, which runs a session "resume validation"
// whenever the tab becomes visible / is restored from bfcache. When those
// requests 503, the component shows the "ComicPile could not reconnect" alert
// and spams the console.
//
// This test drives the real app: it loads the site, confirms it renders, then
// exercises the resume-recovery path the diagnostics point at (a tab
// visibility change via a blur/focus round-trip) and asserts the app is NOT
// left stuck in the reconnect-failed error state that accompanies the spam.
describe("ComicPile console spam (issue #1386)", () => {
  it("loads and recovers without getting stuck in the reconnect-failed state", async (context) => {
    const testdriver = TestDriver(context);

    await testdriver.provision.chrome({
      url: "https://comic-pile.vercel.app/",
    });

    // Give the SPA time to boot (Load was ~1.2s in the report; be generous).
    await testdriver.wait(5000);

    // The app should render its UI, not a blank/error screen.
    const loaded = await testdriver.assert(
      "the ComicPile application UI is visible (not a blank page or an error screen)",
    );
    expect(loaded).toBeTruthy();

    // Trigger the resume-recovery flow the issue's diagnostics point at:
    // ResumeRecovery re-validates the session on visibilitychange -> visible.
    // Open a new tab then close it, forcing the app tab to blur and regain
    // visibility - the same round-trip a user makes when switching tabs.
    await testdriver.pressKeys(["ctrl", "t"]);
    await testdriver.wait(1500);
    await testdriver.pressKeys(["ctrl", "w"]);
    await testdriver.wait(3000);

    // After returning to the app, it must not be stuck showing the
    // "ComicPile could not reconnect" failure alert. If resume validation is
    // 503-ing and spamming the console, this alert is what the user sees.
    const notStuck = await testdriver.assert(
      'the app is NOT showing a "ComicPile could not reconnect" error alert',
    );
    expect(notStuck).toBeTruthy();

    // And the main UI should still be visible and usable.
    const stillUsable = await testdriver.assert(
      "the ComicPile application UI is still visible and usable",
    );
    expect(stillUsable).toBeTruthy();
  });
});
