import { formatters } from "./formatters/all.js";
import { resolveFormatter } from "./resolveFormatter.js";
async function selectFormatter(cwd, { formatter, order, stopDirectory }) {
  if (!formatter) {
    return await resolveFormatter(cwd, { order, stopDirectory });
  }
  const found = formatters.find((f) => f.name === formatter);
  if (!found) {
    throw new Error(
      `Unknown formatter name: ${formatter}. Known formatters are ${formatters.map((formatter2) => formatter2.name).join(", ")}.`
    );
  }
  return found;
}
export {
  selectFormatter
};
