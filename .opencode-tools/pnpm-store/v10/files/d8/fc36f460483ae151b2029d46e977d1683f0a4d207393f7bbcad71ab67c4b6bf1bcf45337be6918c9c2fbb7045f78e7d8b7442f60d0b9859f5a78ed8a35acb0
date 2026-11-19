import { compact } from '../../util/array.js';
import { toConfig, toModule, toDependency } from '../../util/input.js';
import { join, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { contentMapperResolvers } from './content-mappers.js';
const title = 'TypeScript';
const enablers = ['typescript', '@typescript/native', '@typescript/native-preview'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
export const config = ['tsconfig.json'];
const resolveContentMappers = (localConfig, dir) => {
    const inputs = [];
    for (const { package: name, options } of localConfig.contentMappers ?? []) {
        inputs.push(toDependency(name));
        const resolveOptions = contentMapperResolvers.get(name);
        if (resolveOptions && options)
            inputs.push(...resolveOptions(options, dir));
    }
    return inputs;
};
export const resolveConfig = (localConfig, options) => {
    const { compilerOptions } = localConfig;
    const extend = localConfig.extends
        ? [localConfig.extends].flat().map(specifier => toConfig(options.pluginName, specifier))
        : [];
    const references = localConfig.references?.map(({ path }) => toConfig(options.pluginName, path.endsWith('.json') ? path : toAbsolute(join(path, 'tsconfig.json'), options.configFileDir))) ?? [];
    const contentMappers = resolveContentMappers(localConfig, options.configFileDir);
    if (!(compilerOptions && localConfig))
        return compact([...contentMappers, ...extend, ...references]);
    const jsx = (compilerOptions?.jsxImportSource ? [compilerOptions.jsxImportSource] : []).map(id => toDependency(id, { production: true, dir: options.cwd, alsoReferenceOwner: true }));
    const types = compilerOptions.types ?? [];
    const plugins = Array.isArray(compilerOptions?.plugins)
        ? compilerOptions.plugins.map(plugin => (typeof plugin === 'object' && 'name' in plugin ? plugin.name : ''))
        : [];
    const importHelpers = compilerOptions?.importHelpers ? ['tslib'] : [];
    return compact([
        ...contentMappers,
        ...extend,
        ...references,
        ...types.map(id => toModule(id, { isTypeOnly: true, dir: options.cwd, alsoReferenceOwner: true })),
        ...plugins.map(id => toDependency(id, { dir: options.cwd, alsoReferenceOwner: true })),
        ...importHelpers.map(id => toDependency(id, { production: true, dir: options.cwd, alsoReferenceOwner: true })),
        ...jsx,
    ]);
};
export const args = {
    binaries: ['tsc', 'tsgo'],
    string: ['project'],
    alias: { project: ['p'] },
    config: [['project', (p) => (p.endsWith('.json') ? p : join(p, 'tsconfig.json'))]],
};
const note = `[What's up with that configurable tsconfig.json location?](/reference/faq#whats-up-with-that-configurable-tsconfigjson-location)`;
export const docs = { note };
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    args,
};
export default plugin;
