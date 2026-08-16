import { describe, expect, it } from "vitest";
import { TestDriver } from "testdriverai/vitest/hooks";

// TestDriver end-to-end coverage for the Roll rating / action panel
// ("Your Context" completion workflow) described in issue #1406.
//
// Comic Pile (https://comic-pile.vercel.app) allows open self-registration,
// so this suite needs no stored credentials or fixtures: it creates a
// throwaway account through the UI on the live production site, exactly like
// the repo's existing TestDriver smoke/register tests
// (username `td_smoke_*`, password `ProdSmokePass123!`).
//
// The rating panel only appears after a thread has been added and rolled, so
// each test drives: register -> add a thread -> roll -> assert against the
// rating/completion slab. Because these run against production against a fresh
// account, they exercise the REAL mutation/session behavior the issue says
// must be preserved.

const BASE_URL = "https://comic-pile.vercel.app";
const PASSWORD = "ProdSmokePass123!";

function throwawayUser(prefix = "td_roll") {
  const nonce = `${Date.now()}_${Math.floor(Math.random() * 1_000_000)}`;
  return {
    username: `${prefix}_${nonce}`,
    email: `${prefix}_${nonce}@example.com`,
    password: PASSWORD,
  };
}

/**
 * Registers a fresh throwaway account through the UI and lands on the app.
 */
async function registerAndLogin(testdriver, user) {
  await testdriver.provision.chrome({ url: `${BASE_URL}/register` });

  const formVisible = await testdriver.assert(
    "a 'Create Account' registration form with Username, Email, Password and Confirm Password fields is visible",
  );
  expect(formVisible).toBeTruthy();

  await testdriver.find("the Username input field in the registration form").click();
  await testdriver.type(user.username);

  await testdriver.find("the Email input field in the registration form").click();
  await testdriver.type(user.email);

  await testdriver
    .find("the Password input field (not Confirm Password) in the registration form")
    .click();
  await testdriver.type(user.password);

  await testdriver.find("the Confirm Password input field in the registration form").click();
  await testdriver.type(user.password);

  await testdriver.find("the orange 'Create Account' submit button").click();
  await testdriver.wait(4000);

  const loggedIn = await testdriver.assert(
    "the main Comic Pile app is shown after registration (a dice/roll 'Pile Roller' view with an add-a-thread affordance), with no registration error",
  );
  expect(loggedIn).toBeTruthy();
}

/**
 * Adds a single thread so there is something eligible to roll, then rolls the
 * die to reach the rating / completion panel ("Your Context").
 */
async function addThreadAndRoll(testdriver, title) {
  // Open the add-thread affordance.
  await testdriver.find("the '+ Add a Thread' / 'Add Thread' button").click();
  await testdriver.wait(1500);

  await testdriver.find("the thread Title input field in the add/new thread form").click();
  await testdriver.type(title);

  // Save the new thread. Some variants label this Save / Add / Create.
  await testdriver.find("the button that saves/adds the new thread (Save, Add, or Create)").click();
  await testdriver.wait(2500);

  // Roll the die to select this thread and open the rating panel.
  await testdriver.find("the primary Roll / roll-the-die button").click();
  await testdriver.wait(4000);

  const ratingVisible = await testdriver.assert(
    "the rating / completion panel is shown: a 'Your rating' section with a numeric rating value and a rating slider, and a full-width 'Mark read & save' or 'Mark read & complete' primary action",
  );
  expect(ratingVisible).toBeTruthy();
}

describe("Roll rating / action panel (Your Context completion workflow)", () => {
  it("shows the rating value, slider, die consequence and aligned actions", async (context) => {
    const testdriver = TestDriver(context);
    const user = throwawayUser();

    await registerAndLogin(testdriver, user);
    await addThreadAndRoll(testdriver, `Roll Panel ${Date.now()}`);

    // Current rating is shown prominently.
    const ratingValueVisible = await testdriver.assert(
      "a prominent numeric rating value (formatted like '3.0') is displayed under a 'Your rating' label",
    );
    expect(ratingValueVisible).toBeTruthy();

    // Die consequence dN -> dM is shown next to the rating.
    const dieConsequenceVisible = await testdriver.assert(
      "a die consequence in the form 'dN → dM' (for example 'd6 → d4' or 'd6 → d6') is displayed alongside the rating",
    );
    expect(dieConsequenceVisible).toBeTruthy();

    // The queue consequence copy is present.
    const queueConsequenceVisible = await testdriver.assert(
      "a concise queue-consequence sentence is shown (e.g. 'Moves this thread to the front of the queue.' or 'Moves this thread beyond the next roll range.')",
    );
    expect(queueConsequenceVisible).toBeTruthy();

    // Primary action is full width; Snooze and Cancel Roll are equal secondary actions.
    const actionsAligned = await testdriver.assert(
      "a full-width primary 'Mark read & save' (or 'Mark read & complete') action is shown above a row with two aligned secondary actions: 'Snooze' and 'Cancel roll'. The secondary actions are visually balanced (not a stretched Snooze plus a tiny Cancel).",
    );
    expect(actionsAligned).toBeTruthy();
  });

  it("previews the established step-up result for 3.0 on a d6", async (context) => {
    const testdriver = TestDriver(context);
    const user = throwawayUser();

    await registerAndLogin(testdriver, user);
    await addThreadAndRoll(testdriver, `Step Up ${Date.now()}`);

    // Drive the range control to 3.0 using the keyboard for accessible operation.
    await testdriver.find("the 'Your rating' slider (a range input from 0.5 to 5.0)").click();
    // Home sets the slider to its minimum (0.5); five ArrowRight steps reach 3.0.
    await testdriver.pressKeys(["home"]);
    for (let i = 0; i < 5; i += 1) {
      await testdriver.pressKeys(["right"]);
    }
    await testdriver.wait(1000);

    const ratingIsThreeZero = await testdriver.assert(
      "the rating value now reads '3.0'",
    );
    expect(ratingIsThreeZero).toBeTruthy();

    // 3.0 is below the front-of-queue threshold, so the die steps up (more variety).
    const stepUpPreview = await testdriver.assert(
      "the queue consequence indicates the thread moves beyond the next roll range (a below-threshold rating) and the die consequence previews a step-up / 'more variety' result",
    );
    expect(stepUpPreview).toBeTruthy();
  });

  it("previews the established step-down result for 4.0 on a d6", async (context) => {
    const testdriver = TestDriver(context);
    const user = throwawayUser();

    await registerAndLogin(testdriver, user);
    await addThreadAndRoll(testdriver, `Step Down ${Date.now()}`);

    await testdriver.find("the 'Your rating' slider (a range input from 0.5 to 5.0)").click();
    // Home -> 0.5, then seven ArrowRight steps reach 4.0.
    await testdriver.pressKeys(["home"]);
    for (let i = 0; i < 7; i += 1) {
      await testdriver.pressKeys(["right"]);
    }
    await testdriver.wait(1000);

    const ratingIsFourZero = await testdriver.assert(
      "the rating value now reads '4.0'",
    );
    expect(ratingIsFourZero).toBeTruthy();

    // 4.0 is at/above the front-of-queue threshold, so the die steps down (more focused).
    const stepDownPreview = await testdriver.assert(
      "the queue consequence indicates the thread moves to the front of the queue (an at/above-threshold rating) and the die consequence previews a step-down / 'more focused' result",
    );
    expect(stepDownPreview).toBeTruthy();
  });

  it("saves the pending issue and returns to the unrolled state", async (context) => {
    const testdriver = TestDriver(context);
    const user = throwawayUser();

    await registerAndLogin(testdriver, user);
    await addThreadAndRoll(testdriver, `Save Flow ${Date.now()}`);

    await testdriver
      .find("the full-width primary 'Mark read & save' or 'Mark read & complete' button")
      .click();
    await testdriver.wait(4000);

    // After saving, the rating panel is dismissed and the app returns to the
    // unrolled roll view (pending state cleared).
    const returnedToUnrolled = await testdriver.assert(
      "the rating / completion panel is no longer shown; the app has returned to the unrolled roll view (the 'Your rating' slider and 'Mark read & save' action are gone) with no error",
    );
    expect(returnedToUnrolled).toBeTruthy();
  });

  it("snooze is a distinct action from cancel roll", async (context) => {
    const testdriver = TestDriver(context);
    const user = throwawayUser();

    await registerAndLogin(testdriver, user);
    await addThreadAndRoll(testdriver, `Snooze Flow ${Date.now()}`);

    // Snooze and Cancel are both present as distinct secondary actions.
    const bothActionsPresent = await testdriver.assert(
      "both a 'Snooze' action and a separate 'Cancel roll' action are visible as distinct secondary buttons",
    );
    expect(bothActionsPresent).toBeTruthy();

    // Snooze dismisses the panel (distinct from cancel/save semantics).
    await testdriver.find("the 'Snooze' secondary button in the rating action panel").click();
    await testdriver.wait(3500);

    const snoozeDismissedPanel = await testdriver.assert(
      "after snoozing, the rating / completion panel is dismissed and the app returns to the roll view with no error",
    );
    expect(snoozeDismissedPanel).toBeTruthy();
  });

  it("cancel roll dismisses the panel without marking the issue read", async (context) => {
    const testdriver = TestDriver(context);
    const user = throwawayUser();

    await registerAndLogin(testdriver, user);
    await addThreadAndRoll(testdriver, `Cancel Flow ${Date.now()}`);

    await testdriver.find("the 'Cancel roll' secondary button in the rating action panel").click();
    await testdriver.wait(3000);

    const cancelReturnedToPool = await testdriver.assert(
      "after cancelling the roll, the rating / completion panel is dismissed and the app returns to the roll view (the thread was NOT marked read) with no error",
    );
    expect(cancelReturnedToPool).toBeTruthy();
  });
});
