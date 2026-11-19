import { hasDependency } from '../../util/plugin.js';
const title = 'PurgeCSS';
const enablers = ['purgecss', '@fullhuman/postcss-purgecss'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['purgecss.config.js'];
const args = {
    config: true,
};
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
    args,
};
export default plugin;
