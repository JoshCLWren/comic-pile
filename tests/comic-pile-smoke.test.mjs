import { describe, expect, it } from "vitest";
import { TestDriver } from "testdriverai/vitest/hooks";

// Short production smoke test for Comic Pile (https://comic-pile.vercel.app).
//
// Verifies the live site is up and its public auth pages render correctly.
// Requires no credentials or fixtures.
describe("Comic Pile - smoke", () => {
  it("serves the login page on production", async (context) => {
    const testdriver = TestDriver(context);

    await testdriver.provision.chrome({
      url: "https://comic-pile.vercel.app/login",
    });

    // The production login screen should render with its form.
    const loginVisible = await testdriver.assert(
      "the Comic Pile login page is shown with a 'Welcome Back' heading, Username and Password fields, and a 'Sign In' button",
    );
    expect(loginVisible).toBeTruthy();
  });

  it("links from login to the registration page", async (context) => {
    const testdriver = TestDriver(context);

    await testdriver.provision.chrome({
      url: "https://comic-pile.vercel.app/login",
    });

    // A user without an account can navigate to registration.
    await testdriver.find("the link to create a new account / register (e.g. 'Sign up' or 'Create Account')").click();
    await testdriver.wait(2000);

    const registerVisible = await testdriver.assert(
      "the registration page is shown with a 'Create Account' form containing Username, Email, Password and Confirm Password fields",
    );
    expect(registerVisible).toBeTruthy();
  });
});
