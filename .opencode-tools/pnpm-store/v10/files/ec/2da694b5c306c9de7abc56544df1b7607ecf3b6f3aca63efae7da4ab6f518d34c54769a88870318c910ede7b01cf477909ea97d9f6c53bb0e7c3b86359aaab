import * as fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { runPackageFormatterTextCommand } from "./runFormatterCommand.js";
import { wrapSafe } from "./wrapSafe.js";
const biomeConfigFileNames = [
  "biome.json",
  "biome.jsonc",
  ".biome.json",
  ".biome.jsonc"
];
const inProcessFormatters = /* @__PURE__ */ new Map();
async function createInProcessFormatter(cwd) {
  const require2 = createRequire(path.resolve(cwd, "index.js"));
  const readVersion = (packageName) => wrapSafe(
    () => require2(`${packageName}/package.json`).version
  );
  const biomeVersion = readVersion("@biomejs/biome");
  if (!biomeVersion || biomeVersion !== readVersion("@biomejs/wasm-nodejs")) {
    return void 0;
  }
  const api = wrapSafe(() => require2("@biomejs/js-api/nodejs"));
  const config = await findConfiguration(cwd);
  if (!api || config?.configuration.extends || config?.configuration.root === false || config?.configuration.vcs?.enabled && config.configuration.vcs.useIgnoreFile) {
    return void 0;
  }
  const directory = config?.directory ?? cwd;
  const biome = new api.Biome();
  const { projectKey } = biome.openProject(directory);
  if (config) {
    biome.applyConfiguration(projectKey, config.configuration);
  }
  return (filePath, text) => {
    const relativePath = path.relative(directory, filePath);
    const features = biome.workspace?.fileFeatures?.({
      features: ["format"],
      path: relativePath,
      projectKey
    });
    if (features?.featuresSupported.format === "ignored") {
      return { formatted: text };
    }
    const { content, diagnostics } = biome.formatContent(projectKey, text, {
      filePath: relativePath
    });
    return diagnostics.length ? {
      error: new Error(
        diagnostics.map(({ description }) => description).join("\n")
      )
    } : { formatted: content };
  };
}
async function findConfiguration(cwd) {
  let directory = path.resolve(cwd);
  while (true) {
    for (const fileName of biomeConfigFileNames) {
      const text = await fs.readFile(path.join(directory, fileName), "utf8").catch(() => void 0);
      if (text !== void 0) {
        return {
          configuration: parseJsonc(text),
          directory
        };
      }
    }
    const parent = path.dirname(directory);
    if (parent === directory) {
      return void 0;
    }
    directory = parent;
  }
}
function parseJsonc(text) {
  return JSON.parse(
    text.replaceAll(
      /("(?:\\.|[^"\\])*")|\/\/[^\n]*|\/\*[\s\S]*?\*\/|,(?=\s*[}\]])/g,
      (_, string) => string ?? ""
    )
  );
}
const formatTextBiome = async (options) => {
  let inProcessFormatter = inProcessFormatters.get(options.cwd);
  if (!inProcessFormatter) {
    inProcessFormatter = createInProcessFormatter(options.cwd).catch(
      () => void 0
    );
    inProcessFormatters.set(options.cwd, inProcessFormatter);
  }
  const format = await inProcessFormatter;
  if (format) {
    try {
      return format(options.filePath, options.text);
    } catch (error) {
      return { error: error.stackTrace };
    }
  }
  return await runPackageFormatterTextCommand(
    {
      args: (filePath) => ["format", `--stdin-file-path=${filePath}`],
      command: "biome",
      packageName: "@biomejs/biome"
    },
    options
  );
};
export {
  formatTextBiome
};
