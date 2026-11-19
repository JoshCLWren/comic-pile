import { hasDependency } from '../../util/plugin.js';
const title = 'Expressive Code';
const enablers = [
    'astro-expressive-code',
    'rehype-expressive-code',
    '@astrojs/starlight',
];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['ec.config.{js,mjs,cjs,ts}'];
export default {
    title,
    enablers,
    isEnabled,
    entry,
};
