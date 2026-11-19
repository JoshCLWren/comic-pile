import { toConfig, toDependency, toEntryPath } from '../../util/input.js';
import { dirname, isInternal, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { getInputsFromSettings } from '../eslint/helpers.js';
const title = 'Oxlint';
const enablers = ['oxlint', 'vite-plus'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['.oxlintrc.{json,jsonc}', 'oxlint.config.{ts,mts}'];
const args = {
    config: true,
};
const resolveJsPlugins = (jsPlugins, configFilePath) => {
    const inputs = [];
    const dir = dirname(configFilePath);
    for (const plugin of jsPlugins ?? []) {
        const specifier = typeof plugin === 'string' ? plugin : plugin.specifier;
        if (!isInternal(specifier))
            inputs.push(toDependency(specifier));
        else
            inputs.push(toEntryPath(toAbsolute(specifier, dir)));
    }
    return inputs;
};
export const resolveExtendedConfig = (config, configFilePath) => {
    const inputs = [];
    for (const entry of config.extends ?? []) {
        if (typeof entry === 'string') {
            const filePath = toAbsolute(entry, dirname(configFilePath));
            inputs.push(toConfig('oxlint', filePath));
        }
        else {
            for (const input of resolveExtendedConfig(entry, configFilePath))
                inputs.push(input);
        }
    }
    for (const input of resolveJsPlugins(config.jsPlugins, configFilePath))
        inputs.push(input);
    for (const override of config.overrides ?? []) {
        for (const input of resolveJsPlugins(override.jsPlugins, configFilePath))
            inputs.push(input);
        for (const input of getInputsFromSettings(override.settings))
            inputs.push(input);
    }
    for (const input of getInputsFromSettings(config.settings))
        inputs.push(input);
    return inputs;
};
const resolveConfig = (config, options) => resolveExtendedConfig(config, options.configFilePath);
const isFilterTransitiveDependencies = true;
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    isFilterTransitiveDependencies,
    args,
};
export default plugin;
