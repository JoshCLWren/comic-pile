export { _load as load } from './loader.js';
import { arrayify } from './array.js';
import { loadFile } from './fs.js';
import { _load as load } from './loader.js';
import { get } from './object.js';
import { basename } from './path.js';
export const hasDependency = (dependencies, values) => values.some(value => {
    if (typeof value === 'string') {
        return dependencies.has(value);
    }
    if (value instanceof RegExp) {
        for (const dependency of dependencies) {
            if (value.test(dependency))
                return true;
        }
    }
    return false;
});
export const normalizePluginConfig = (pluginConfig) => {
    if (typeof pluginConfig === 'boolean')
        return pluginConfig;
    if (typeof pluginConfig === 'string' || Array.isArray(pluginConfig)) {
        return { config: pluginConfig ? arrayify(pluginConfig) : null, entry: null, project: [] };
    }
    const config = pluginConfig.config === undefined ? null : arrayify(pluginConfig.config);
    const entry = pluginConfig.entry === undefined ? null : arrayify(pluginConfig.entry);
    const project = pluginConfig.project === undefined
        ? (entry ?? []).filter(pattern => !pattern.startsWith('!'))
        : arrayify(pluginConfig.project);
    return { config, entry, project };
};
export const loadConfigForPlugin = async (configFilePath, plugin, options, pluginName) => {
    const { packageJsonPath } = plugin;
    const { manifest } = options;
    if (basename(configFilePath) === 'package.json') {
        return typeof packageJsonPath === 'function'
            ? packageJsonPath(manifest)
            : get(manifest, packageJsonPath ?? pluginName);
    }
    return plugin.parseConfig ? await plugin.parseConfig(await loadFile(configFilePath)) : await load(configFilePath);
};
