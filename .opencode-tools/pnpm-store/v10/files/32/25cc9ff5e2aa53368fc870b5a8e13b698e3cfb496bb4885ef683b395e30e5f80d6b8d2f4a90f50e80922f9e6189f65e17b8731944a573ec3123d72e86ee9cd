import { compact } from '../../util/array.js';
import { toConfig, toModule, toDependency } from '../../util/input.js';
import { getPackageNameFromSpecifier } from '../../util/modules.js';
import { isInNodeModules } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { api, resolveName } from './helpers.js';
const title = 'Babel';
const enablers = [/^@babel\//];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = [
    'babel.config.{json,js,cjs,mjs,cts,ts,mts}',
    '.babelrc.{json,js,cjs,mjs,cts}',
    '.babelrc',
    'package.json',
];
const getName = (value) => [Array.isArray(value) ? value[0] : value].filter(name => typeof name === 'string');
const DECORATOR_TRANSFORMS = 'decorator-transforms';
const isRuntimeImportPlugin = (value) => {
    if (!Array.isArray(value) || typeof value[0] !== 'string')
        return false;
    if (getPackageNameFromSpecifier(resolveName(value[0], 'plugin')) !== DECORATOR_TRANSFORMS)
        return false;
    const runtime = value[1]?.runtime;
    return typeof runtime?.import === 'string';
};
const toPluginModule = (id) => toModule(id, isInNodeModules(id) ? { optional: true } : undefined);
export const getDependenciesFromConfig = (config, isProduction = true) => {
    const presets = config.presets?.flatMap(getName).map(name => resolveName(name, 'preset')) ?? [];
    const plugins = config.plugins?.flatMap(getName).map(name => resolveName(name, 'plugin')) ?? [];
    const toInputs = (config) => getDependenciesFromConfig(config, isProduction);
    const nested = config.env ? Object.values(config.env).flatMap(toInputs) : [];
    const overrides = config.overrides ? [config.overrides].flat().flatMap(toInputs) : [];
    return compact([
        ...presets.map(toPluginModule),
        ...plugins.map(toPluginModule),
        ...(plugins.includes('@babel/plugin-transform-runtime')
            ? [toDependency('@babel/runtime', { optional: true, production: isProduction })]
            : []),
        ...(config.plugins?.some(isRuntimeImportPlugin)
            ? [toDependency(DECORATOR_TRANSFORMS, { production: isProduction })]
            : []),
        ...nested,
        ...overrides,
    ]);
};
const getExtendedConfigs = (config) => [
    ...(config.extends ? [toConfig('babel', config.extends)] : []),
    ...Object.values(config.env ?? {}).flatMap(getExtendedConfigs),
    ...(config.overrides ?? []).flatMap(getExtendedConfigs),
];
const resolveConfig = async (config) => {
    if (typeof config === 'function')
        config = config(api);
    if (!config)
        return [];
    return [...getExtendedConfigs(config), ...getDependenciesFromConfig(config)];
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
