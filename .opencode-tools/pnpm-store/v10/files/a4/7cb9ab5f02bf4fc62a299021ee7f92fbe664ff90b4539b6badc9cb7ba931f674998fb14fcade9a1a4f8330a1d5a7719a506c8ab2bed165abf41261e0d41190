import { createRequire } from "node:module";
import path from "node:path";
import { limitConcurrency } from "./limitConcurrency.js";
import { runPackageFormatterCommand } from "./runFormatterCommand.js";
import { wrapSafe } from "./wrapSafe.js";
const prettierInternalCliModules = [
  "prettier/internal/legacy-cli.mjs",
  "prettier/internal/cli.mjs"
];
const args = ["--write", "--ignore-unknown"];
function requirePrettierInternalCli(cwd) {
  const require2 = createRequire(path.resolve(cwd, "index.js"));
  for (const moduleName of prettierInternalCliModules) {
    const prettierCli = wrapSafe(
      () => require2(moduleName)
    );
    if (prettierCli) {
      return prettierCli;
    }
  }
  return void 0;
}
const runPrettierCli = limitConcurrency(
  async (prettierCli, rawArguments) => {
    const previousExitCode = process.exitCode;
    process.exitCode = void 0;
    try {
      await prettierCli.run(rawArguments);
      return readExitCode();
    } finally {
      process.exitCode = previousExitCode;
    }
  },
  1
);
function readExitCode() {
  return Number(process.exitCode ?? 0);
}
const runPrettier = async ({
  cwd,
  dryRun,
  patterns
}) => {
  const prettierCli = path.resolve(cwd) === process.cwd() ? requirePrettierInternalCli(cwd) : void 0;
  if (!prettierCli) {
    return await runPackageFormatterCommand(
      { args, command: "prettier" },
      { cwd, dryRun, patterns }
    );
  }
  if (dryRun) {
    return {
      args: [...args, ...patterns],
      command: "prettier",
      runner: "dry-run"
    };
  }
  return {
    code: await runPrettierCli(prettierCli, [
      "--log-level",
      "warn",
      ...args,
      ...patterns
    ]),
    runner: "virtual"
  };
};
export {
  runPrettier
};
