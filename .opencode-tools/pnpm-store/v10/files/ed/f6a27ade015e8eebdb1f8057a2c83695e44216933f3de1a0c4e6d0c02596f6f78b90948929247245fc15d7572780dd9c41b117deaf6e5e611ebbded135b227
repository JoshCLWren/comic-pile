import * as fs from "node:fs/promises";
import path from "node:path";
import { runFormatterTextCommand } from "./runFormatterCommand.js";
async function isExcludedByDeno(options) {
  try {
    await fs.access(options.filePath);
  } catch {
    return false;
  }
  const result = await runFormatterTextCommand(
    { args: (filePath) => ["fmt", "--check", filePath], command: "deno" },
    options
  );
  return !!result.error?.message.includes("No target files found");
}
const formatTextDeno = async (options) => {
  const extension = path.extname(options.filePath).slice(1);
  if (!extension) {
    return {
      error: new Error(
        `deno fmt can't infer a file type without an extension: ${options.filePath}`
      )
    };
  }
  const [excluded, result] = await Promise.all([
    isExcludedByDeno(options),
    runFormatterTextCommand(
      { args: () => ["fmt", "--ext", extension, "-"], command: "deno" },
      options
    )
  ]);
  return excluded ? { formatted: options.text } : result;
};
export {
  formatTextDeno
};
