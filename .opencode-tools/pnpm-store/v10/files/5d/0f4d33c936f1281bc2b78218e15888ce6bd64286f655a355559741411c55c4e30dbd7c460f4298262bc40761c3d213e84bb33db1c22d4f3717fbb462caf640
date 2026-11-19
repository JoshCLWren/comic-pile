import { toModule, toDependency, toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Gatsby';
const enablers = ['gatsby', 'gatsby-cli'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['gatsby-{config,node}.{js,mjs,jsx,ts,tsx}', 'plugins/**/gatsby-node.{js,mjs,jsx,ts,tsx}'];
const production = [
    'gatsby-{browser,ssr}.{js,jsx,ts,tsx}',
    'src/api/**/*.{js,ts}',
    'src/pages/**/*.{js,jsx,ts,tsx}',
    'src/templates/**/*.{js,jsx,ts,tsx}',
    'src/html.{js,jsx,ts,tsx}',
    'plugins/**/gatsby-{browser,ssr}.{js,jsx,ts,tsx}',
];
const resolveConfig = async (localConfig, options) => {
    const { configFileName } = options;
    const entries = production.map(id => toEntry(id, { production: true }));
    if (configFileName.includes('gatsby-config')) {
        const plugins = localConfig.plugins ?? [];
        return [...entries, ...plugins.map(plugin => toModule(typeof plugin === 'string' ? plugin : plugin.resolve))];
    }
    if (configFileName.includes('gatsby-node')) {
        const plugins = new Set();
        const actions = { setBabelPlugin: plugin => plugins.add(plugin.name) };
        const _config = localConfig;
        if (typeof _config.onCreateBabelConfig === 'function') {
            _config.onCreateBabelConfig({ actions });
        }
        return [...entries, ...Array.from(plugins, id => toDependency(id))];
    }
    return entries;
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
