import { hasDependency } from '../../util/plugin.js';
const title = 'Rslint';
const enablers = ['@rslint/core'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['rslint.config.{js,mjs,ts,mts}'];
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
