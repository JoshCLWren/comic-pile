import { hasDependency } from '../../util/plugin.js';
const title = 'Remix';
const enablers = ['@remix-run/dev'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['remix.config.{js,cjs,mjs}', 'remix.init/index.js'];
const production = [
    'app/root.{js,jsx,ts,tsx}',
    'app/entry.{client,server}.{js,jsx,ts,tsx}',
    'app/routes/**/*.{js,jsx,ts,tsx}',
    'server.{js,ts}',
];
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
    production,
};
export default plugin;
