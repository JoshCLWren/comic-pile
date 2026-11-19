import { isDirectory } from '../../util/fs.js';
import { _syncGlob } from '../../util/glob.js';
import { toAlias, toConfig, toModule, toEntryPath, toDependency, toEntry, toIgnore } from '../../util/input.js';
import { loadTSConfig } from '../../util/load-tsconfig.js';
import { isInternal, join, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { buildAutoImportMap, collectLocalImportPaths, createAutoImportMaps, createTsCompiler, createVueCompiler, readAndParseFile, } from '../_vue/auto-import.js';
const title = 'Nuxt';
const enablers = ['nuxt', 'nuxt-nightly'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['nuxt.config.{js,cjs,mjs,ts,cts,mts}'];
const scriptExt = '{js,mjs,cjs,jsx,ts,mts,cts,tsx}';
const entry = [`app.config.${scriptExt}`, '**/*.d.vue.ts'];
const app = ['app.{vue,jsx,tsx}', 'error.{vue,jsx,tsx}', 'router.options.ts'];
const layout = (dir = 'layouts') => join(dir, '**/*.{vue,jsx,tsx}');
const middleware = (dir = 'middleware') => [join(dir, `*.${scriptExt}`), join(dir, `*/index.${scriptExt}`)];
const pages = (dir = 'pages') => join(dir, '**/*.{vue,jsx,tsx}');
const plugins = (dir = 'plugins') => [join(dir, `*.${scriptExt}`), join(dir, `*/index.${scriptExt}`)];
const modules = 'modules/**/*.{ts,vue}';
const server = ['api/**/*.ts', 'middleware/**/*.ts', 'plugins/**/*.ts', 'routes/**/*.ts', 'tasks/**/*.ts'];
const production = [
    ...app,
    layout(),
    ...middleware(),
    pages(),
    ...plugins(),
    modules,
    ...server.map(id => join('server', id)),
];
const setup = async () => {
    if (globalThis && !('defineNuxtConfig' in globalThis)) {
        Object.defineProperty(globalThis, 'defineNuxtConfig', {
            value: (id) => id,
            writable: true,
            configurable: true,
        });
    }
};
const resolve = () => [
    toIgnore('^#build/', 'unresolved'),
    toIgnore('#components', 'unresolved'),
    toIgnore('#imports', 'unresolved'),
    toIgnore('^#internal/', 'unresolved'),
    toIgnore('#spa-template', 'unresolved'),
];
const resolveAlias = (specifier, srcDir, rootDir) => {
    if (specifier.startsWith('~~/') || specifier.startsWith('@@/'))
        return join(rootDir, specifier.slice(3));
    if (specifier.startsWith('~/') || specifier.startsWith('@/'))
        return join(srcDir, specifier.slice(2));
    return specifier;
};
const remoteSourcePrefixes = ['gh:', 'github:', 'gitlab:', 'bitbucket:', 'https://', 'http://'];
const toLayerSource = (layer) => {
    if (typeof layer === 'string')
        return layer;
    if (Array.isArray(layer))
        return layer[0];
    if (layer && typeof layer === 'object' && 'source' in layer)
        return layer.source;
};
const toLayerSources = (extend) => {
    const sources = [];
    if (!extend)
        return sources;
    for (const layer of Array.isArray(extend) ? extend : [extend]) {
        const source = toLayerSource(layer);
        if (typeof source === 'string')
            sources.push(source);
    }
    return sources;
};
const addAppEntries = (inputs, srcDir, serverDir, config, dir) => {
    for (const id of entry)
        inputs.push(toEntry(join(srcDir, id)));
    for (const id of app)
        inputs.push(toEntry(join(srcDir, id), { production: true }));
    inputs.push(toEntry(join(srcDir, layout(config.dir?.layouts)), { production: true }));
    for (const id of middleware(config.dir?.middleware))
        inputs.push(toEntry(join(srcDir, id), { production: true }));
    inputs.push(toEntry(join(srcDir, pages(config.dir?.pages)), { production: true }));
    for (const id of plugins(config.dir?.plugins))
        inputs.push(toEntry(join(srcDir, id), { production: true }));
    inputs.push(toEntry(join(srcDir, 'components/global/**/*.{vue,jsx,tsx}'), { production: true }));
    for (const id of server)
        inputs.push(toEntry(join(dir, serverDir, id), { production: true }));
    inputs.push(toEntry(join(dir, modules), { production: true }));
    if (config.css)
        for (const id of config.css)
            inputs.push(toEntryPath(resolveAlias(id, srcDir, dir), { production: true }));
};
const findLayerConfigs = (cwd) => _syncGlob({ cwd, patterns: [`layers/*/${config.at(0)}`] });
const definitionFiles = [
    '.nuxt/imports.d.ts',
    '.nuxt/components.d.ts',
    '.nuxt/types/nitro-routes.d.ts',
    '.nuxt/types/nitro-imports.d.ts',
];
const registerCompilers = async ({ cwd, hasDependency, registerCompiler }) => {
    if (hasDependency('nuxt') || hasDependency('nuxt-nightly') || isDirectory(cwd, '.nuxt')) {
        const paths = definitionFiles.map(file => join(cwd, file));
        const maps = createAutoImportMaps();
        for (const path of paths) {
            buildAutoImportMap(path, readAndParseFile(path), maps, path.endsWith('components.d.ts'));
        }
        registerCompiler({ extension: '.vue', compiler: createVueCompiler(maps, cwd) });
        registerCompiler({ extension: '.ts', compiler: createTsCompiler(maps) });
    }
};
const resolveConfig = async (localConfig, options) => {
    const { configFileDir: cwd } = options;
    const hasAppDir = isDirectory(cwd, 'app');
    const srcDir = toAbsolute(localConfig.srcDir ?? (hasAppDir ? join(cwd, 'app') : cwd), cwd);
    const serverDir = localConfig.serverDir ?? 'server';
    const inputs = [];
    const addModule = (id) => {
        const specifier = resolveAlias(id, srcDir, cwd);
        inputs.push(isInternal(specifier)
            ? toEntryPath(specifier, { production: true })
            : toDependency(specifier, { production: true }));
    };
    for (const id of localConfig.modules ?? []) {
        if (Array.isArray(id) && typeof id[0] === 'string')
            addModule(id[0]);
        if (typeof id === 'string')
            addModule(id);
    }
    for (const id of localConfig.plugins ?? []) {
        const src = typeof id === 'string' ? id : id?.src;
        if (typeof src === 'string')
            inputs.push(toModule(resolveAlias(src, srcDir, cwd), { dir: cwd, production: true }));
    }
    addAppEntries(inputs, srcDir, serverDir, localConfig, cwd);
    const sharedDir = toAbsolute(localConfig.dir?.shared ?? 'shared', cwd);
    inputs.push(toAlias('#shared', sharedDir));
    inputs.push(toAlias('#shared/*', join(sharedDir, '*'), { dir: cwd }));
    const aliases = localConfig.alias;
    if (aliases) {
        for (const key in aliases) {
            const prefix = resolveAlias(aliases[key], srcDir, cwd);
            inputs.push(toAlias(key, prefix));
            if (prefix.endsWith('/') || isDirectory(prefix)) {
                inputs.push(toAlias(join(key, '*'), join(prefix, '*'), { dir: cwd }));
            }
        }
    }
    for (const source of toLayerSources(localConfig.extends)) {
        if (remoteSourcePrefixes.some(prefix => source.startsWith(prefix)))
            continue;
        const target = resolveAlias(source, srcDir, cwd);
        const resolved = isInternal(target) ? toAbsolute(target, cwd) : target;
        const configs = _syncGlob({ cwd: resolved, patterns: config });
        if (configs.length > 0)
            for (const cfg of configs)
                inputs.push(toConfig('nuxt', cfg));
        else
            inputs.push(isInternal(target) ? toDependency(source) : toDependency(source, { production: true }));
    }
    for (const layerConfig of findLayerConfigs(cwd)) {
        inputs.push(toConfig('nuxt', layerConfig));
    }
    if (cwd !== options.cwd)
        return inputs;
    for (const file of _syncGlob({ cwd, patterns: ['.nuxt/module/*.d.ts'] })) {
        const result = readAndParseFile(file);
        for (const p of collectLocalImportPaths(file, result))
            inputs.push(toEntryPath(p, { production: true }));
    }
    const dir = join(cwd, '.nuxt');
    const tsConfig = await loadTSConfig(join(dir, 'tsconfig.json'));
    const paths = tsConfig.compilerOptions?.paths;
    if (paths) {
        for (const key in paths) {
            if (key === '#imports' || key === '#components')
                continue;
            inputs.push(toAlias(key, paths[key], { dir }));
        }
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    production,
    setup,
    resolve,
    resolveConfig,
    registerCompilers,
};
export default plugin;
