import { toConfig, toDependency, toEntryPath } from '../../util/input.js';
import { toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { findWebpackDependenciesFromConfig } from '../webpack/index.js';
const title = 'Electron Forge';
const enablers = ['@electron-forge/cli'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const packageJsonPath = 'config.forge';
const config = ['package.json', 'forge.config.{js,mjs,cjs,ts,mts,cts}'];
const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const isPlainObject = (value) => isObject(value) && Object.getPrototypeOf(value) === Object.prototype;
const toArray = (value) => (Array.isArray(value) ? value : value === undefined ? [] : [value]);
const toStrings = (value) => {
    const values = [];
    for (const item of isObject(value) ? Object.values(value) : toArray(value)) {
        if (typeof item === 'string')
            values.push(item);
    }
    return values;
};
const getPluginInputs = async (name, opts, options) => {
    if (!isObject(opts))
        return [];
    const { cwd, configFilePath } = options;
    const inputs = [];
    const addEntry = (value) => {
        for (const id of toStrings(value))
            inputs.push(toEntryPath(toAbsolute(id, cwd), { production: true }));
    };
    const addConfig = async (pluginName, value) => {
        if (typeof value === 'string') {
            inputs.push(toConfig(pluginName, value, { dir: cwd, containingFilePath: configFilePath }));
        }
        else if (pluginName === 'webpack' && isObject(value)) {
            for (const input of await findWebpackDependenciesFromConfig(value, options))
                inputs.push(input);
        }
    };
    if (name === 'vite' || name === '@electron-forge/plugin-vite') {
        for (const build of toArray(opts.build)) {
            if (!isObject(build))
                continue;
            addEntry(build.entry);
            await addConfig('vite', build.config);
        }
        for (const renderer of toArray(opts.renderer))
            if (isObject(renderer))
                await addConfig('vite', renderer.config);
    }
    else if (name === 'webpack' || name === '@electron-forge/plugin-webpack') {
        await addConfig('webpack', opts.mainConfig);
        for (const renderer of toArray(opts.renderer)) {
            if (!isObject(renderer))
                continue;
            await addConfig('webpack', renderer.config);
            for (const entryPoint of toArray(renderer.entryPoints)) {
                if (!isObject(entryPoint))
                    continue;
                addEntry(entryPoint.js);
                if (!isObject(entryPoint.preload))
                    continue;
                addEntry(entryPoint.preload.js);
                await addConfig('webpack', entryPoint.preload.config);
            }
        }
    }
    return inputs;
};
const resolveConfig = async (localConfig, options) => {
    if (typeof localConfig === 'string') {
        return [toConfig('electron-forge', localConfig, { containingFilePath: options.configFilePath })];
    }
    if (!isObject(localConfig))
        return [];
    const inputs = [];
    for (const item of [localConfig.makers, localConfig.publishers, localConfig.plugins].flatMap(toArray)) {
        if (!isObject(item))
            continue;
        if (isPlainObject(item) && typeof item.name === 'string')
            inputs.push(toDependency(item.name));
        for (const input of await getPluginInputs(item.name, item.config, options))
            inputs.push(input);
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    packageJsonPath,
    config,
    resolveConfig,
};
export default plugin;
