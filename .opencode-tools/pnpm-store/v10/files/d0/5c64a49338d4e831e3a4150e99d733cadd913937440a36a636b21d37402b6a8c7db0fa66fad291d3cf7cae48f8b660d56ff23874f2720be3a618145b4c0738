import path from "node:path";
import { selectFormatter } from "./selectFormatter.js";
async function format(text, options) {
  if (!options.filePath.trim()) {
    return {
      message: "No file path was provided to format.",
      ran: false
    };
  }
  const { cwd = process.cwd() } = options;
  const formatter = await selectFormatter(cwd, options);
  if (!formatter) {
    return { message: "Could not detect a formatter.", ran: false };
  }
  return {
    formatter,
    ran: true,
    ...await formatter.formatText({
      cwd,
      filePath: path.resolve(cwd, options.filePath),
      text
    })
  };
}
export {
  format
};
