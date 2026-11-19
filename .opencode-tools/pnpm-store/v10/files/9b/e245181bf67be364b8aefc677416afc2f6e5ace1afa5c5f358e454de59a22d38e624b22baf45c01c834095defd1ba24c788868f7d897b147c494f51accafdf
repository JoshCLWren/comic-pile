import { selectFormatter } from "./selectFormatter.js";
async function formatly(patterns, options = {}) {
  if (!patterns.join("").trim()) {
    return {
      message: "No file patterns were provided to formatly.",
      ran: false
    };
  }
  const { cwd = process.cwd(), dryRun } = options;
  const formatter = await selectFormatter(cwd, options);
  if (!formatter) {
    return { message: "Could not detect a formatter.", ran: false };
  }
  return {
    formatter,
    ran: true,
    result: await formatter.runner({ cwd, dryRun, patterns })
  };
}
export {
  formatly
};
