import { describe, expect, it } from "vitest";
import { TestDriver } from "testdriverai/vitest/hooks";

// Sample TestDriver test for Comic Pile (https://comic-pile.vercel.app).
//
// Comic Pile lets anyone self-register, so this test needs no stored
// credentials or fixtures: it creates a throwaway account through the UI on
// the live production site, exactly like the repo's existing Playwright
// smoke tests do (username `smoke_*`, password `ProdSmokePass123!`).
describe("Comic Pile - registration", () => {
  it("registers a new user and lands on the app", async (context) => {
    const testdriver = TestDriver(context);

    // Unique throwaway user so the test can be re-run against production.
    const nonce = `${Date.now()}_${Math.floor(Math.random() * 1_000_000)}`;
    const username = `td_smoke_${nonce}`;
    const email = `td_smoke_${nonce}@example.com`;
    const password = "ProdSmokePass123!";

    await testdriver.provision.chrome({
      url: "https://comic-pile.vercel.app/register",
    });

    // The registration form should be visible.
    const formVisible = await testdriver.assert(
      "a 'Create Account' registration form with Username, Email, Password and Confirm Password fields is visible",
    );
    expect(formVisible).toBeTruthy();

    // Fill in the registration form with the throwaway account.
    await testdriver.find("the Username input field in the registration form").click();
    await testdriver.type(username);

    await testdriver.find("the Email input field in the registration form").click();
    await testdriver.type(email);

    await testdriver
      .find("the Password input field (not Confirm Password) in the registration form")
      .click();
    await testdriver.type(password);

    await testdriver.find("the Confirm Password input field in the registration form").click();
    await testdriver.type(password);

    // Submit.
    await testdriver.find("the orange 'Create Account' submit button").click();

    // Registration should log the user in and drop them on the main app.
    await testdriver.wait(4000);

    const loggedIn = await testdriver.assert(
      "the main Comic Pile app is shown after registration - a 'Pile Roller' dice/roll view with an '+ Add a Thread' button is visible, and no registration error is shown",
    );
    expect(loggedIn).toBeTruthy();
  });
});
