import { toModule, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Prettier';
const enablers = ['prettier'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = [
    '.prettierrc',
    '.prettierrc.{json,js,cjs,mjs,ts,cts,mts,yml,yaml,toml,json5}',
    'prettier.config.{js,cjs,mjs,ts,cts,mts}',
    'package.{json,yaml}',
];
const resolveConfig = config => {
    if (typeof config === 'string')
        return [toModule(config)];
    const result = new Set();
    const processOptions = (options) => {
        if (Array.isArray(options.plugins)) {
            for (const plugin of options.plugins) {
                if (typeof plugin === 'string') {
                    result.add(isInternal(plugin) ? toModule(plugin) : toDependency(plugin));
                }
            }
        }
    };
    processOptions(config);
    if (config.overrides) {
        for (const override of config.overrides) {
            if (override.options) {
                processOptions(override.options);
            }
        }
    }
    return Array.from(result);
};
const args = {
    config: ['config'],
    resolve: ['plugin'],
};
const isFilterTransitiveDependencies = true;
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    args,
    resolveConfig,
    isFilterTransitiveDependencies,
};
export default plugin;
