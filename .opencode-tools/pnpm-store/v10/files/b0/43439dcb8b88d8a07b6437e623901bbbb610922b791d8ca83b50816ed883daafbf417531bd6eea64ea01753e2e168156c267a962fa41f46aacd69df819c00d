import { toConfig, toModule, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { toCosmiconfig } from '../../util/plugin-config.js';
const title = 'commitlint';
const enablers = ['@commitlint/cli'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = [
    'package.json',
    'package.yaml',
    ...toCosmiconfig('commitlint', { additionalExtensions: ['cts', 'mts'] }),
];
const toExtendsSpecifier = (id) => {
    if (id.startsWith('@'))
        return id.includes('/') ? id : `${id}/commitlint-config`;
    return id.startsWith('commitlint-config-') ? id : `commitlint-config-${id}`;
};
const toPluginSpecifier = (id) => {
    if (!id.startsWith('@'))
        return id.startsWith('commitlint-plugin-') ? id : `commitlint-plugin-${id}`;
    const [scope, name] = id.split('/');
    if (!name)
        return `${scope}/commitlint-plugin`;
    if (name === 'commitlint-plugin' || name.startsWith('commitlint-plugin-'))
        return id;
    return id.replace('/', '/commitlint-plugin-');
};
const resolveConfig = async (config) => {
    const inputs = [];
    const extendsConfigs = [];
    for (const id of config.extends ? [config.extends].flat() : []) {
        if (isInternal(id))
            inputs.push(toConfig('commitlint', id));
        else
            extendsConfigs.push(toExtendsSpecifier(id));
    }
    const plugins = [];
    for (const id of config.plugins ? [config.plugins].flat() : []) {
        if (typeof id === 'string')
            plugins.push(toPluginSpecifier(id));
    }
    for (const id of [...extendsConfigs, ...plugins])
        inputs.push(toDependency(id));
    const parserPreset = await config.parserPreset;
    const modules = config.formatter ? [config.formatter] : [];
    if (typeof parserPreset === 'string')
        modules.push(parserPreset);
    for (const id of modules)
        inputs.push(isInternal(id) ? toModule(id) : toDependency(id));
    if (typeof parserPreset === 'object' && parserPreset.path)
        inputs.push(toDependency(parserPreset.path));
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
