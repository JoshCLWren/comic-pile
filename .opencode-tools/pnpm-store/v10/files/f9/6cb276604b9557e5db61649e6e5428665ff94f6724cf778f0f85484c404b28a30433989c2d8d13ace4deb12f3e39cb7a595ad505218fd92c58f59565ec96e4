import { toDependency } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
import { toCosmiconfig } from '../../util/plugin-config.js';
const title = 'SVGR';
const enablers = ['@svgr/cli', '@svgr/core'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['package.json', ...toCosmiconfig('svgr')];
const resolveConfig = async (config) => {
    const inputs = [];
    if (config.plugins) {
        for (const plugin of config.plugins) {
            if (typeof plugin === 'string')
                inputs.push(toDependency(plugin));
        }
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
