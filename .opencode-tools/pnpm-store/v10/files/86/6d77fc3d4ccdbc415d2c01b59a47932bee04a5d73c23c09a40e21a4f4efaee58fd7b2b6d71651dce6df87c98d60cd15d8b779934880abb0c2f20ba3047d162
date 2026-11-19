import { toEntryPath, toEntry } from '../../util/input.js';
import { toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'TanStack Router';
const enablers = [
    '@tanstack/react-router',
    '@tanstack/solid-router',
    '@tanstack/vue-router',
    '@tanstack/svelte-router',
    '@tanstack/router-cli',
    '@tanstack/router-plugin',
    '@tanstack/react-start',
    '@tanstack/solid-start',
];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['tsr.config.json'];
const routerEntries = ['src/{router,start,client,server}.{js,jsx,ts,tsx}'];
const production = ['src/routeTree.gen.{ts,js}', ...routerEntries];
const resolveConfig = async (localConfig, options) => {
    const { configFileDir } = options;
    const generatedRouteTree = localConfig.generatedRouteTree ?? './src/routeTree.gen.ts';
    const routeTreePath = toAbsolute(generatedRouteTree, configFileDir);
    return [
        toEntryPath(routeTreePath, { production: true }),
        ...routerEntries.map(id => toEntry(id, { production: true })),
    ];
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
