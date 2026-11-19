import { createRequire } from "node:module";
import { formatly } from "./formatly.js";
const dryRunFlag = "--dry-run";
const helpFlags = /* @__PURE__ */ new Set(["--help", "-h"]);
const versionFlags = /* @__PURE__ */ new Set(["--version", "-v"]);
const help = `Usage: formatly [--dry-run] <patterns...>

Formats files with whatever formatter your project is already using.

Options:
  --dry-run      Report the detected formatter and command without formatting
  -h, --help     Show this help message
  -v, --version  Show formatly's version`;
async function cli(args) {
  if (args.some((arg) => helpFlags.has(arg))) {
    console.log(help);
    return 0;
  }
  if (args.some((arg) => versionFlags.has(arg))) {
    const require2 = createRequire(import.meta.url);
    const { version } = require2("../package.json");
    console.log(version);
    return 0;
  }
  const dryRun = args.includes(dryRunFlag);
  const patterns = args.filter((arg) => arg !== dryRunFlag);
  let result;
  try {
    result = await formatly(patterns, { dryRun });
  } catch (error) {
    console.error(`Failed running formatly: ${String(error)} \u{1F6D1}`);
    return 1;
  }
  if (!result.ran) {
    console.error(result.message);
    return 1;
  }
  if (result.result.runner === "dry-run") {
    const { args: args2, command } = result.result;
    console.log(`Detected ${result.formatter.name}. \u{1F50D}`);
    console.log(`Would run: ${[command, ...args2].join(" ")}`);
    return 0;
  }
  if (result.result.runner === "child_process" && result.result.signal) {
    console.error(
      `Failed formatting with ${result.formatter.name} (signal ${result.result.signal}). \u{1F6D1}`
    );
    return 1;
  }
  const { code } = result.result;
  if (code) {
    console.error(
      `Failed formatting with ${result.formatter.name} (exit code ${code.toString()}). \u{1F6D1}`
    );
    return code;
  }
  console.log(`Formatted with ${result.formatter.name}. \u{1F9FC}`);
  return 0;
}
export {
  cli
};
