import { createRequire } from "node:module";
import path from "node:path";
import { runPackageFormatterTextCommand } from "./runFormatterCommand.js";
import { wrapSafe } from "./wrapSafe.js";
function requirePrettier(cwd) {
  const require2 = createRequire(path.resolve(cwd, "index.js"));
  return wrapSafe(() => require2("prettier"));
}
const formatTextPrettier = async (options) => {
  const prettier = requirePrettier(options.cwd);
  if (!prettier) {
    return await runPackageFormatterTextCommand(
      {
        args: (filePath2) => ["--stdin-filepath", filePath2],
        command: "prettier"
      },
      options
    );
  }
  const { filePath, text } = options;
  try {
    const fileInfo = await prettier.getFileInfo(filePath, {
      ignorePath: [
        path.join(options.cwd, ".prettierignore"),
        path.join(options.cwd, ".gitignore")
      ],
      resolveConfig: true
    });
    if (fileInfo.ignored) {
      return { formatted: text };
    }
    if (!fileInfo.inferredParser) {
      return {
        error: new Error(`No parser could be inferred for file: ${filePath}`)
      };
    }
    const config = await prettier.resolveConfig(filePath, {
      editorconfig: true
    });
    return {
      formatted: await prettier.format(text, { ...config, filepath: filePath })
    };
  } catch (error) {
    return {
      error: error instanceof Error ? error : new Error(String(error))
    };
  }
};
export {
  formatTextPrettier
};
