import { hasDependency } from '../../util/plugin.js';
const title = 'dependency-cruiser';
const enablers = ['dependency-cruiser'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = ['.dependency-cruiser.{js,cjs,mjs,json}'];
const args = {
    binaries: ['depcruise', 'dependency-cruise', 'dependency-cruiser', 'depcruise-baseline'],
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
