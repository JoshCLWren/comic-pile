import { hasDependency } from '../../util/plugin.js';
import { resolveFromAST } from './resolveFromAST.js';
const title = 'vite-plugin-pwa';
const enablers = ['vite-plugin-pwa', '@vite-pwa/nuxt'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['vite.config.{js,mjs,ts,cjs,mts,cts}', 'nuxt.config.{js,cjs,mjs,ts,cts,mts}'];
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveFromAST,
};
export default plugin;
