import { hasDependency } from '../../util/plugin.js';
const title = 'Danger';
const enablers = ['danger'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['dangerfile.{js,cjs,mjs,ts,mts}', 'Dangerfile.{js,mjs,ts,mts}'];
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
};
export default plugin;
