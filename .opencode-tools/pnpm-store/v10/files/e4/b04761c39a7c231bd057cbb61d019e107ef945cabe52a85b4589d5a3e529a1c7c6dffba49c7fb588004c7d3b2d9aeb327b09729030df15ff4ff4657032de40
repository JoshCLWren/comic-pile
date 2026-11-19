import { collectFirstPropertyValue } from '../../typescript/ast-helpers.js';
import { isDirectory } from '../../util/fs.js';
import { toEntryPath, toEntry } from '../../util/input.js';
import { join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Flue';
const enablers = ['@flue/runtime'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['flue.config.{ts,mts,mjs,js,cjs,cts}'];
const extensions = '{ts,mts,js,mjs}';
const entryNames = ['app', 'db', 'cloudflare'];
const agentsPattern = `{agent,agents/*,agents/*/agent}.${extensions}`;
const production = [`{.flue/,src/,}{app,db,cloudflare}.${extensions}`, `{.flue/,src/,}${agentsPattern}`];
const getSourceRoot = (dir) => {
    for (const name of ['.flue', 'src'])
        if (isDirectory(dir, name))
            return join(dir, name);
    return dir;
};
const resolveFromAST = (program, { configFileDir }) => {
    const sourceRoot = getSourceRoot(configFileDir);
    const inputs = [];
    for (const name of entryNames) {
        const filePath = collectFirstPropertyValue(program, name);
        if (filePath)
            inputs.push(toEntryPath(join(configFileDir, filePath), { production: true }));
        else
            inputs.push(toEntry(join(sourceRoot, `${name}.${extensions}`), { production: true }));
    }
    const agents = collectFirstPropertyValue(program, 'agents') ?? agentsPattern;
    inputs.push(toEntry(join(sourceRoot, agents), { production: true }));
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    production,
    resolveFromAST,
};
export default plugin;
