import * as fs from "node:fs/promises";
import path from "node:path";
import { createOutputError } from "./formatters/runFormatterCommand.js";
import { selectFormatter } from "./selectFormatter.js";
async function formatFiles(filePaths, options = {}) {
  if (!filePaths.length) {
    return {
      message: "No file paths were provided to format.",
      ran: false
    };
  }
  const { check, cwd = process.cwd() } = options;
  const formatter = await selectFormatter(cwd, options);
  if (!formatter) {
    return { message: "Could not detect a formatter.", ran: false };
  }
  const absolutePaths = filePaths.map(
    (filePath) => path.resolve(cwd, filePath)
  );
  return {
    formatter,
    ran: true,
    ...check ? await formatter.checker({ cwd, filePaths: absolutePaths }) : await writeFiles(formatter, cwd, absolutePaths)
  };
}
async function readFiles(filePaths) {
  return await Promise.all(
    filePaths.map(
      (filePath) => fs.readFile(filePath, "utf8").catch(() => void 0)
    )
  );
}
async function writeFiles(formatter, cwd, filePaths) {
  const before = await readFiles(filePaths);
  const result = await formatter.runner({ cwd, patterns: filePaths }).catch((error) => error);
  if (result instanceof Error) {
    return { error: result };
  }
  const signal = result.runner === "child_process" ? result.signal : null;
  if (result.runner !== "dry-run" && (result.code || signal)) {
    return {
      error: createOutputError(formatter.name, { code: result.code, signal })
    };
  }
  const after = await readFiles(filePaths);
  return {
    changed: filePaths.filter((_, index) => before[index] !== after[index])
  };
}
export {
  formatFiles
};
