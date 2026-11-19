import { toDependency, toEntryPath } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
const RULE_PREFIX = 'textlint-rule-';
const PRESET_PREFIX = 'textlint-rule-preset-';
const FILTER_RULE_PREFIX = 'textlint-filter-rule-';
const PLUGIN_PREFIX = 'textlint-plugin-';
const createFullPackageName = (prefix, name) => {
    if (name.charAt(0) === '@') {
        const scopedName = name.slice(name.indexOf('/') + 1);
        if (scopedName !== prefix && !scopedName.startsWith(`${prefix}-`)) {
            return name.replace(/^@([^/]+)\/(.*)$/, `@$1/${prefix}$2`);
        }
    }
    return `${prefix}${name}`;
};
const hasPrefix = (prefix, name) => (name.charAt(0) === '@' ? name.slice(name.indexOf('/') + 1) : name).startsWith(prefix);
const isDeclared = (manifest, name) => Boolean(manifest.dependencies?.[name] ??
    manifest.devDependencies?.[name] ??
    manifest.optionalDependencies?.[name] ??
    manifest.peerDependencies?.[name]);
const toPackageDependency = (prefix, name, candidates, manifest) => toDependency(candidates.find(candidate => isDeclared(manifest, candidate)) ??
    (hasPrefix(prefix, name) ? name : createFullPackageName(prefix, name)));
const isPresetRuleKey = (key) => key.startsWith('preset-') ||
    key.startsWith(PRESET_PREFIX) ||
    (key.charAt(0) === '@' && (key.includes('/preset-') || key.includes(`/${PRESET_PREFIX}`)));
const toPresetDependency = (key, manifest) => {
    const name = key.replace(/^preset-/, '').replace(/^@([^/]+)\/preset-(.*)$/, '@$1/$2');
    const candidates = [`${PRESET_PREFIX}${name}`, name, createFullPackageName(PRESET_PREFIX, name), key];
    return toPackageDependency(PRESET_PREFIX, name, candidates, manifest);
};
const toModuleDependency = (prefix, key, manifest) => toPackageDependency(prefix, key, [createFullPackageName(prefix, key), key], manifest);
const toLocalEntry = (key, cwd) => toEntryPath(key, { dir: cwd });
export const toRuleDependency = (key, manifest, cwd) => {
    if (isInternal(key))
        return toLocalEntry(key, cwd);
    return isPresetRuleKey(key) ? toPresetDependency(key, manifest) : toModuleDependency(RULE_PREFIX, key, manifest);
};
export const toFilterRuleDependency = (key, manifest, cwd) => isInternal(key) ? toLocalEntry(key, cwd) : toModuleDependency(FILTER_RULE_PREFIX, key, manifest);
export const toPluginDependency = (key, manifest, cwd) => isInternal(key) ? toLocalEntry(key, cwd) : toModuleDependency(PLUGIN_PREFIX, key, manifest);
