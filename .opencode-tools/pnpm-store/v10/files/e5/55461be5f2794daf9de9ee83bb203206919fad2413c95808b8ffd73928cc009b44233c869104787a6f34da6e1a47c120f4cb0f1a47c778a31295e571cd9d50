import { toAlias, toDependency } from '../../util/input.js';
import { join } from '../../util/path.js';
const environments = {
    node: null,
    jsdom: null,
    'happy-dom': null,
    'edge-runtime': null,
};
const envPackageNames = {
    jsdom: 'jsdom',
    'happy-dom': 'happy-dom',
    'edge-runtime': '@edge-runtime/vm',
};
const getEnvSpecifier = (env) => {
    if (env in envPackageNames)
        return envPackageNames[env];
    return `vitest-environment-${env}`;
};
export const toEnvDependency = (env) => toDependency(getEnvSpecifier(env), env === 'nuxt' ? { optional: true } : undefined);
const builtInReporters = [
    'agent',
    'basic',
    'blob',
    'default',
    'dot',
    'github-actions',
    'hanging-process',
    'html',
    'json',
    'junit',
    'minimal',
    'tap',
    'tap-flat',
    'tree',
    'verbose',
];
const addStar = (value) => (value.endsWith('*') ? value : join(value, '*').replace(/\/\*\*$/, '/*'));
const getAliasEntries = (aliasOptions) => {
    if (!Array.isArray(aliasOptions))
        return Object.entries(aliasOptions);
    const entries = [];
    for (const { find, replacement } of aliasOptions)
        if (typeof find === 'string')
            entries.push([find, replacement]);
    return entries;
};
export const getAliasInputs = (aliasOptions, cwd) => {
    const inputs = [];
    for (const [alias, value] of getAliasEntries(aliasOptions)) {
        if (!value)
            continue;
        const prefixes = [value].flat().filter((value) => typeof value === 'string');
        if (alias.length > 1)
            inputs.push(toAlias(alias, prefixes, { dir: cwd }));
        inputs.push(toAlias(addStar(alias), prefixes.map(addStar), { dir: cwd }));
    }
    return inputs;
};
export const getExternalReporters = (reporters) => reporters
    ? [reporters]
        .flat()
        .map(reporter => (Array.isArray(reporter) ? reporter[0] : reporter))
        .filter((reporter) => typeof reporter === 'string' && !builtInReporters.includes(reporter))
    : [];
