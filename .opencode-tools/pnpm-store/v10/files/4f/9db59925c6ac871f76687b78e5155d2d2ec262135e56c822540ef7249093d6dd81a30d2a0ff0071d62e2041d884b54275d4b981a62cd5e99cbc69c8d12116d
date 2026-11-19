import { toDependency, toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'WXT';
const enablers = ['wxt'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['wxt.config.{js,cjs,mjs,ts,cts,mts}'];
const production = ['entrypoints/**/*'];
const resolveConfig = async (localConfig) => {
    const inputs = [];
    for (const pattern of production) {
        inputs.push(toEntry(pattern, { production: true }));
    }
    for (const id of localConfig?.modules ?? []) {
        if (typeof id === 'string')
            inputs.push(toDependency(id));
    }
    return inputs;
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
