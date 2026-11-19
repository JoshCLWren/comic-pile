import { hasDependency } from '../../util/plugin.js';
import { args as typescriptArgs, config, resolveConfig } from '../typescript/index.js';
const title = 'tsrs';
const enablers = ['tsrs'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const args = { ...typescriptArgs, binaries: ['tsrs'] };
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    args,
};
export default plugin;
