import { hasDependency } from '../../util/plugin.js';
import { config, resolveConfig } from '../serverless-framework/index.js';
const title = 'osls';
const enablers = ['osls'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
