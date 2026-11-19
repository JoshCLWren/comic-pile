import { hasDependency } from '../../util/plugin.js';
const title = 'Lingui';
const enablers = ['@lingui/cli'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['lingui.config.{js,cjs,ts,mjs}', '.linguirc.{js,ts}'];
const args = {
    config: ['config'],
};
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
    args,
};
export default plugin;
