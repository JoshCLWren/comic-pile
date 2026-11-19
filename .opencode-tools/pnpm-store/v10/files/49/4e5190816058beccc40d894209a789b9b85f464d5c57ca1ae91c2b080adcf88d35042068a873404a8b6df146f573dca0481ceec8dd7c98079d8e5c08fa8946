import { toConfig, toModule, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { toCosmiconfig } from '../../util/plugin-config.js';
const title = 'Semantic Release';
const enablers = ['semantic-release'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const isRootOnly = true;
const packageJsonPath = 'release';
const config = ['package.json', ...toCosmiconfig('release')];
const excludePackages = [
    '@semantic-release/commit-analyzer',
    '@semantic-release/github',
    '@semantic-release/npm',
    '@semantic-release/release-notes-generator',
];
const resolveConfig = (config, options) => {
    const inputs = [];
    for (const id of [config?.extends ?? []].flat()) {
        if (isInternal(id))
            inputs.push(toConfig('semantic-release', id, { containingFilePath: options.configFilePath }));
        else
            inputs.push(toDependency(id));
    }
    const plugins = (config?.plugins ?? []).map(plugin => (Array.isArray(plugin) ? plugin[0] : plugin));
    for (const id of plugins.filter(plugin => !excludePackages.includes(plugin)))
        inputs.push(toModule(id));
    return inputs;
};
const args = {
    alias: { extends: ['e'] },
    resolveInputs: (parsed, { cwd }) => {
        if (parsed.extends === 'false')
            return [];
        const inputs = [];
        for (const value of [parsed.extends ?? []].flat()) {
            for (const part of String(value).split(',')) {
                const id = part.trim();
                if (isInternal(id))
                    inputs.push(toConfig('semantic-release', id, { dir: cwd }));
                else
                    inputs.push(toDependency(id));
            }
        }
        return inputs;
    },
};
const plugin = {
    title,
    enablers,
    isEnabled,
    isRootOnly,
    packageJsonPath,
    config,
    resolveConfig,
    args,
};
export default plugin;
