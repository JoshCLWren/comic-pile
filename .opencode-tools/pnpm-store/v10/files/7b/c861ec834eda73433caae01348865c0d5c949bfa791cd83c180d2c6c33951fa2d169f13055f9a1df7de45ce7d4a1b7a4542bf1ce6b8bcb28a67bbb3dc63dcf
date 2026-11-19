import { toModule, toDependency, toEntry } from '../../util/input.js';
import { isInternal, join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { extractFunctionsConfigProperty } from './helpers.js';
const title = 'Netlify';
const enablers = [/^@netlify\/plugin-/, 'netlify-cli', '@netlify/functions'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['netlify.toml'];
const NETLIFY_FUNCTIONS_DIR = 'netlify/functions';
const NETLIFY_FUNCTIONS_EXTS = 'js,mjs,cjs,ts,mts,cts';
const production = [`${NETLIFY_FUNCTIONS_DIR}/**/*.{${NETLIFY_FUNCTIONS_EXTS}}`];
const toPluginInput = (id) => {
    const specifier = id.startsWith('/') ? `.${id}` : id;
    return isInternal(specifier) ? toModule(specifier) : toDependency(id);
};
const resolveConfig = async (localConfig) => {
    return [
        ...extractFunctionsConfigProperty(localConfig.functions || {}, 'included_files'),
        join(localConfig.functions?.directory ?? NETLIFY_FUNCTIONS_DIR, `**/*.{${NETLIFY_FUNCTIONS_EXTS}}`),
    ]
        .filter(file => !file.startsWith('!'))
        .map(id => toEntry(id, { production: true }))
        .concat([
        ...(localConfig?.plugins?.map(plugin => plugin.package) ?? []).map(toPluginInput),
        ...extractFunctionsConfigProperty(localConfig.functions || {}, 'external_node_modules').map(id => toDependency(id, { production: true })),
    ]);
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    production,
    resolveConfig,
};
export default plugin;
