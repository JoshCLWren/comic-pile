import { toEntry } from '../../util/input.js';
import { join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import expo from '../expo/index.js';
import { getConfig } from '../expo/helpers.js';
const title = 'Expo Router';
const enablers = ['expo-router'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = expo.config;
const production = ['app/**/*.{js,jsx,ts,tsx}', 'src/app/**/*.{js,jsx,ts,tsx}'];
const resolveConfig = async (localConfig, options) => {
    const config = getConfig(localConfig, options);
    for (const plugin of config.plugins ?? []) {
        if (!Array.isArray(plugin))
            continue;
        const [name, pluginOptions] = plugin;
        const root = pluginOptions?.root;
        if (name === 'expo-router' && typeof root === 'string') {
            return [toEntry(join(root, '**/*.{js,jsx,ts,tsx}'), { production: true })];
        }
    }
    return production.map(id => toEntry(id, { production: true }));
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
