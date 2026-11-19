import { hasDependency } from '../../util/plugin.js';
const title = 'Plop';
const enablers = ['plop'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['plopfile.{cjs,mjs,js,ts}'];
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
};
export default plugin;
