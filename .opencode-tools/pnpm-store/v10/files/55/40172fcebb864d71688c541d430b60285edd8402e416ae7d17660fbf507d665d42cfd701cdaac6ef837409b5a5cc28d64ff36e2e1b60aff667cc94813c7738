import { toConfig, toIgnore } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
import { getDependencies } from './helpers.js';
const title = 'Expo';
const enablers = ['expo'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['app.json', 'app.config.{json,ts,js,mts,cts,mjs,cjs}'];
const resolve = () => [toConfig('babel', 'babel.config'), toIgnore('babel-preset-expo', 'unresolved')];
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolve,
    resolveConfig: getDependencies,
};
export default plugin;
