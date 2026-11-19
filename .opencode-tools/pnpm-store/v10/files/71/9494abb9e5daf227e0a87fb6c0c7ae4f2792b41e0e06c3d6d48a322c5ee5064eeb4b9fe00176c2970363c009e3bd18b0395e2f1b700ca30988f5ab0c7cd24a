import { isAbsolute, toRelative } from './path.js';
export const fromBinary = (input) => input.specifier;
export const toBinary = (specifier, options = {}) => ({
    type: 'binary',
    specifier,
    ...options,
});
export const isBinary = (input) => input.type === 'binary';
export const toCatalog = (specifier, catalogName) => ({
    type: 'catalog',
    specifier,
    catalogName,
});
export const isCatalog = (input) => input.type === 'catalog';
export const toEntry = (specifier, options = {}) => ({
    type: 'entry',
    specifier,
    ...options,
});
export const isEntry = (input) => input.type === 'entry' && !input.production;
export const toProject = (specifier) => ({ type: 'project', specifier });
export const isProject = (input) => input.type === 'project';
export const isProductionEntry = (input) => input.type === 'entry' && input.production === true;
export const toConfig = (pluginName, specifier, options = {}) => ({
    type: 'config',
    specifier,
    pluginName,
    ...options,
});
export const isConfig = (input) => input.type === 'config';
export const toDependency = (specifier, options = {}) => ({
    type: 'dependency',
    specifier,
    ...options,
});
export const isDependency = (input) => input.type === 'dependency';
export const toModule = (specifier, options = {}) => ({
    type: 'deferResolve',
    specifier,
    ...options,
});
export const isDeferResolve = (input) => input.type === 'deferResolve';
export const toEntryPath = (specifier, options = {}) => ({
    type: 'deferResolveEntry',
    specifier,
    ...options,
});
export const isDeferResolveEntry = (input) => input.type === 'deferResolveEntry';
export const toAlias = (specifier, prefix, options = {}) => ({
    type: 'alias',
    specifier,
    prefixes: Array.isArray(prefix) ? prefix : [prefix],
    ...options,
});
export const isAlias = (input) => input.type === 'alias';
export const toIgnore = (specifier, issueType) => ({
    type: 'ignore',
    specifier,
    issueType,
});
export const isIgnore = (input) => input.type === 'ignore';
export const toDebugString = (input, cwd) => `${input.type}:${isAbsolute(input.specifier) ? toRelative(input.specifier, cwd) : input.specifier}${input.containingFilePath ? ` (${toRelative(input.containingFilePath, cwd)})` : ''}`;
