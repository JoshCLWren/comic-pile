import { spawn } from "child_process";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  detect
} from "package-manager-detector";
import { resolveCommand } from "package-manager-detector/commands";
import { limitConcurrency } from "./limitConcurrency.js";
const agentsExecutingPackageNames = /* @__PURE__ */ new Set(["bun", "npm"]);
function createOutputError(command, {
  code,
  signal,
  stderr = ""
}) {
  const reason = signal === null ? `exited with code ${String(code)}` : `was terminated by signal ${signal}`;
  return new Error(
    [`${path.basename(command)} ${reason}.`, stderr.trim()].filter(Boolean).join("\n")
  );
}
async function runFormatterCheckCommand({ args, ...check }, { cwd, filePaths }) {
  return await spawnFormatterCheckCommand(
    check,
    { args: args(filePaths), command: check.command },
    { cwd, filePaths }
  );
}
async function runFormatterCommand({ args, command }, { cwd, dryRun, patterns }) {
  return await spawnFormatterCommand(
    { args: [...args, ...patterns], command },
    cwd,
    dryRun
  );
}
async function runFormatterTextCommand({ args, command }, { cwd, filePath, text }) {
  return await spawnFormatterTextCommand(
    { args: args(filePath), command },
    cwd,
    text
  );
}
async function runPackageFormatterCheckCommand({ args, command, packageName, ...check }, { cwd, filePaths }) {
  return await spawnFormatterCheckCommand(
    check,
    await resolvePackageCommand({ command, packageName }, args(filePaths), cwd),
    { cwd, filePaths }
  );
}
async function runPackageFormatterCommand({ args, ...source }, { cwd, dryRun, patterns }) {
  return await spawnFormatterCommand(
    await resolvePackageCommand(source, [...args, ...patterns], cwd),
    cwd,
    dryRun
  );
}
async function runPackageFormatterTextCommand({ args, ...source }, { cwd, filePath, text }) {
  return await spawnFormatterTextCommand(
    await resolvePackageCommand(source, args(filePath), cwd),
    cwd,
    text
  );
}
async function resolvePackageCommand({ command, packageName = command }, args, cwd) {
  const bin = await findLocalBin(command, cwd);
  if (bin) {
    return { args, command: bin };
  }
  const agent = (await detect({ cwd }))?.agent ?? "npm";
  const executable = agentsExecutingPackageNames.has(agent) ? packageName : command;
  return resolveCommand(agent, "execute-local", [executable, ...args]) ?? {
    args: [packageName, ...args],
    command: "npx"
  };
}
async function findLocalBin(command, cwd) {
  if (process.platform === "win32") {
    return void 0;
  }
  let directory = path.resolve(cwd);
  while (true) {
    const bin = path.join(directory, "node_modules", ".bin", command);
    try {
      await fs.access(bin);
      return bin;
    } catch {
      const parent = path.dirname(directory);
      if (parent === directory) {
        return void 0;
      }
      directory = parent;
    }
  }
}
async function resolveRealPaths(filePaths) {
  return await Promise.all(
    filePaths.map((filePath) => fs.realpath(filePath).catch(() => filePath))
  );
}
async function spawnFormatterCheckCommand({
  differencesCode = 1,
  parse,
  parseFailures
}, resolved, { cwd, filePaths }) {
  const output = await spawnOutput(resolved, cwd);
  if (output.error) {
    return { error: output.error };
  }
  if (output.code === 0 || output.code === differencesCode) {
    const failures = parseFailures?.(output) ?? [];
    if (failures.length) {
      return {
        error: createOutputError(resolved.command, {
          ...output,
          stderr: failures.join("\n")
        })
      };
    }
    const listed = new Set(
      await resolveRealPaths(
        parse(output).map((filePath) => path.resolve(cwd, filePath))
      )
    );
    const realFilePaths = await resolveRealPaths(filePaths);
    return {
      changed: filePaths.filter((_, index) => listed.has(realFilePaths[index]))
    };
  }
  return { error: createOutputError(resolved.command, output) };
}
async function spawnFormatterCommand({ args, command }, cwd, dryRun) {
  if (dryRun) {
    return { args, command, runner: "dry-run" };
  }
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      stdio: ["ignore", "ignore", "inherit"]
    });
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      resolve({
        code,
        runner: "child_process",
        signal
      });
    });
  });
}
const spawnFormatterTextCommand = limitConcurrency(
  spawnFormatterTextProcess,
  os.availableParallelism()
);
async function spawnFormatterTextProcess(resolved, cwd, text) {
  const output = await spawnOutput(resolved, cwd, text);
  if (output.error) {
    return { error: output.error };
  }
  if (output.code === 0) {
    return { formatted: output.stdout };
  }
  return { error: createOutputError(resolved.command, output) };
}
async function spawnOutput({ args, command }, cwd, text = "") {
  return await new Promise((resolve) => {
    const child = spawn(command, args, { cwd, stdio: "pipe" });
    const stderr = [];
    const stdout = [];
    child.stderr.on("data", (data) => stderr.push(data));
    child.stdout.on("data", (data) => stdout.push(data));
    child.on("error", (error) => {
      resolve({ error });
    });
    child.on("close", (code, signal) => {
      resolve({
        code,
        signal,
        stderr: Buffer.concat(stderr).toString(),
        stdout: Buffer.concat(stdout).toString()
      });
    });
    child.stdin.on("error", () => void 0);
    child.stdin.end(text);
  });
}
export {
  createOutputError,
  resolvePackageCommand,
  runFormatterCheckCommand,
  runFormatterCommand,
  runFormatterTextCommand,
  runPackageFormatterCheckCommand,
  runPackageFormatterCommand,
  runPackageFormatterTextCommand
};
