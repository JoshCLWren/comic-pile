import { arrayify } from '../../util/array.js';
import { toEntryPath, toDependency } from '../../util/input.js';
import { _load } from '../../util/loader.js';
import { get } from '../../util/object.js';
import { isInternal, join, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Serverless Framework';
const enablers = ['serverless'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
export const config = ['serverless.{js,cjs,mjs,ts,cts,mts,yml,yaml}'];
const fileVariable = /^\$\{file\(([^()$]+)\)(?::([^\s,}]+))?/;
const isRecord = (value) => typeof value === 'object' && value !== null;
const resolveFileVariable = async (value, dir) => {
    const match = typeof value === 'string' && value.match(fileVariable);
    if (!match)
        return value;
    try {
        const content = await _load(toAbsolute(match[1].trim(), dir));
        return match[2] ? get(content, match[2]) : content;
    }
    catch {
        return undefined;
    }
};
const handlerToEntry = (handler, dir) => {
    const dot = handler.lastIndexOf('.');
    const file = handler.slice(0, dot);
    return toEntryPath(file, { production: true, dir });
};
const pluginToInput = (plugin, dir) => isInternal(plugin) ? toEntryPath(toAbsolute(plugin, dir), { production: true }) : toDependency(plugin);
const getFunctionEntries = async (functions, dir, cwd) => {
    const entries = [];
    const resolved = await resolveFileVariable(functions, dir);
    for (const group of Array.isArray(resolved) ? resolved : [resolved]) {
        const fns = await resolveFileVariable(group, dir);
        if (!isRecord(fns))
            continue;
        for (const name in fns) {
            const fn = await resolveFileVariable(fns[name], dir);
            if (isRecord(fn) && typeof fn.handler === 'string')
                entries.push(handlerToEntry(fn.handler, cwd));
        }
    }
    return entries;
};
const getInjectEntries = (esbuild, dir) => esbuild && typeof esbuild === 'object'
    ? arrayify(esbuild.inject).map(id => toEntryPath(join(dir, id), { production: true }))
    : [];
export const resolveConfig = async (config, options) => {
    const functions = await getFunctionEntries(config.functions, options.configFileDir, options.cwd);
    const resolvedPlugins = await resolveFileVariable(config.plugins, options.configFileDir);
    const plugins = Array.isArray(resolvedPlugins)
        ? resolvedPlugins.filter((plugin) => typeof plugin === 'string')
        : [];
    const esbuild = config.custom?.esbuild || config.build?.esbuild ? [toDependency('esbuild', { optional: true })] : [];
    const injectEntries = [
        ...getInjectEntries(config.custom?.esbuild, options.configFileDir),
        ...getInjectEntries(config.build?.esbuild, options.configFileDir),
    ];
    return [
        ...functions,
        ...plugins.map(plugin => pluginToInput(plugin, options.configFileDir)),
        ...esbuild,
        ...injectEntries,
    ];
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
