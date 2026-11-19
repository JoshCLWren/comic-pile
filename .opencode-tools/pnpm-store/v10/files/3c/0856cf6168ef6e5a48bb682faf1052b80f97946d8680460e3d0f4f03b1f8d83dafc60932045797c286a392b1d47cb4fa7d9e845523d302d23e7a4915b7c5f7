import { compact } from '../../util/array.js';
import { toConfig, toModule, toDependency } from '../../util/input.js';
import { getPackageNameFromFilePath, getPackageNameFromModuleSpecifier } from '../../util/modules.js';
import { extname, isAbsolute, isInternal } from '../../util/path.js';
import { substringBefore } from '../../util/string.js';
import { getDependenciesFromConfig } from '../babel/index.js';
export const isFlatConfig = (fileName) => /eslint\.config/.test(fileName);
export const getInputs = (config, options) => {
    const { configFileName } = options;
    if (extname(configFileName) === '.json' || !isFlatConfig(configFileName)) {
        return getInputsDeprecated(config, options);
    }
    const configArray = Array.isArray(config) ? config : [config];
    const dependencies = configArray.flatMap(config => config.settings ? getDependenciesFromSettings(config.settings) : []);
    dependencies.push('eslint-import-resolver-typescript');
    return compact(dependencies).map(id => toModule(id, { optional: true }));
};
const getInputsDeprecated = (config, options) => {
    const extendsList = config.extends ? [config.extends].flat() : [];
    const extendsSpecifiers = compact(extendsList.map(resolveExtendSpecifier));
    if (extendsSpecifiers.some(specifier => specifier?.startsWith('eslint-plugin-prettier')))
        extendsSpecifiers.push('eslint-config-prettier');
    const extendConfigs = [...extendsList.filter(isInternal), ...extendsSpecifiers].map(specifier => toConfig('eslint', specifier));
    const plugins = config.plugins ? config.plugins.map(resolvePluginSpecifier) : [];
    const parsers = getParsers(config);
    const babelDependencies = config.parserOptions?.babelOptions
        ? getDependenciesFromConfig(config.parserOptions.babelOptions, false)
        : [];
    const settings = config.settings ? getDependenciesFromSettings(config.settings) : [];
    const rules = getDependenciesFromRules({});
    const overrides = config.overrides ? [config.overrides].flat().flatMap(d => getInputsDeprecated(d, options)) : [];
    const dependencies = compact([...extendsSpecifiers, ...plugins, ...rules]).map(id => toDependency(id));
    const resolvers = compact(settings).map(id => toModule(id));
    return [...extendConfigs, ...dependencies, ...resolvers, ...parsers, ...babelDependencies, ...overrides];
};
const isParserObject = (value) => typeof value.parseForESLint === 'function' || typeof value.parse === 'function';
export const toParser = (name) => toModule(name, name === 'espree' ? { optional: true } : {});
const getParsers = ({ parser, parserOptions }) => {
    const inputs = [];
    for (const value of [parser, parserOptions?.parser]) {
        if (typeof value === 'string')
            inputs.push(toParser(value));
        else if (value && typeof value === 'object' && !isParserObject(value)) {
            for (const name of Object.values(value))
                if (typeof name === 'string')
                    inputs.push(toParser(name));
        }
    }
    return inputs;
};
const isQualifiedSpecifier = (specifier) => specifier === 'eslint' ||
    /\/eslint-(config|plugin)$/.test(specifier) ||
    /.+eslint-(config|plugin)\//.test(specifier) ||
    /eslint-(config|plugin)-/.test(specifier);
const resolveSpecifier = (namespace, rawSpecifier) => {
    const specifier = rawSpecifier.replace(/(^plugin:|:.+$)/, '');
    if (isQualifiedSpecifier(specifier))
        return specifier;
    if (!specifier.startsWith('@')) {
        const id = rawSpecifier.startsWith('plugin:')
            ? getPackageNameFromModuleSpecifier(specifier)
            : substringBefore(specifier, '/');
        return `${namespace}-${id}`;
    }
    const [scope, name, ...rest] = specifier.split('/');
    if (rawSpecifier.startsWith('plugin:') && rest.length === 0)
        return [scope, namespace].join('/');
    return [scope, name ? `${namespace}-${name}` : namespace, ...rest].join('/');
};
const resolvePluginSpecifier = (specifier) => resolveSpecifier('eslint-plugin', specifier);
const resolveExtendSpecifier = (specifier) => {
    if (isInternal(specifier))
        return;
    const namespace = specifier.startsWith('plugin:') ? 'eslint-plugin' : 'eslint-config';
    return resolveSpecifier(namespace, specifier);
};
const getDependenciesFromRules = (rules = {}) => Object.keys(rules).flatMap(ruleKey => ruleKey.includes('/') ? [resolveSpecifier('eslint-plugin', ruleKey.split('/').slice(0, -1).join('/'))] : []);
const getResolverNames = (value) => {
    if (typeof value === 'string')
        return [value];
    if (Array.isArray(value))
        return value.flatMap(getResolverNames);
    if (value && typeof value === 'object') {
        if ('name' in value && 'resolver' in value)
            return [];
        return Object.keys(value);
    }
    return [];
};
export const importSettingKinds = new Map([
    ['import/resolver', 'resolver'],
    ['import-x/resolver', 'resolver'],
    ['import-x/resolver-legacy', 'resolver'],
    ['import/parsers', 'parsers'],
    ['import-x/parsers', 'parsers'],
]);
const getDependenciesFromSettings = (settings = {}) => {
    return Object.entries(settings).flatMap(([settingKey, settings]) => {
        const kind = importSettingKinds.get(settingKey);
        if (kind === 'resolver') {
            return getResolverNames(settings)
                .filter(key => key !== 'node')
                .map(key => {
                if (isInternal(key))
                    return key;
                if (isAbsolute(key))
                    return getPackageNameFromFilePath(key);
                return `eslint-import-resolver-${key}`;
            });
        }
        if (kind === 'parsers') {
            return (typeof settings === 'string' ? [settings] : Object.keys(settings)).map(key => {
                if (isAbsolute(key))
                    return getPackageNameFromFilePath(key);
                return key;
            });
        }
    });
};
export const getInputsFromSettings = (settings) => compact(getDependenciesFromSettings(settings)).map(id => toModule(id, { optional: true }));
const builtinFormatters = new Set(['html', 'json-with-metadata', 'json', 'stylish']);
const builtinFormattersUntilV8 = new Set([
    'checkstyle',
    'compact',
    'jslint-xml',
    'junit',
    'tap',
    'unix',
    'visualstudio',
]);
const normalizeFormatterName = (name) => {
    if (!name.startsWith('@'))
        return name.startsWith('eslint-formatter-') ? name : `eslint-formatter-${name}`;
    const [scope, id] = name.split('/');
    if (!id)
        return `${scope}/eslint-formatter`;
    return /^eslint-formatter(-|$)/.test(id) ? name : name.replace('/', '/eslint-formatter-');
};
export const resolveFormatters = (formatters, manifest) => {
    const inputs = new Set();
    const isBeforeV9 = (manifest.getMajor('eslint') ?? 9) < 9;
    for (const rawFormatter of [formatters].flat()) {
        const formatter = rawFormatter.replace(/\\/g, '/');
        if (!formatter.startsWith('@') && formatter.includes('/')) {
            inputs.add(toModule(isInternal(formatter) ? formatter : `./${formatter}`));
        }
        else {
            const isBuiltin = builtinFormatters.has(formatter) || (isBeforeV9 && builtinFormattersUntilV8.has(formatter));
            inputs.add(toDependency(normalizeFormatterName(formatter), isBuiltin ? { optional: true } : {}));
        }
    }
    return inputs;
};
