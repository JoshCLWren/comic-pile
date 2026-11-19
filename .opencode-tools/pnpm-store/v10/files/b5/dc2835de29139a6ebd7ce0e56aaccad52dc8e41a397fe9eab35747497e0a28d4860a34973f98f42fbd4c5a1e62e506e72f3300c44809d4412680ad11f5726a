import { toConfig, toDependency } from '../../util/input.js';
import { isAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { resolvePackageManifestPath } from '../../util/resolve.js';
const title = 'WebdriverIO';
const enablers = ['@wdio/cli'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['wdio.conf.{js,cjs,mjs,ts,cts,mts}'];
const getNames = (plugins = []) => plugins.flatMap(plugin => {
    const name = Array.isArray(plugin) ? plugin[0] : plugin;
    return typeof name === 'string' && !name.startsWith('file://') && !isAbsolute(name) ? [name] : [];
});
const toPluginDependency = (name, type, dir) => {
    if (name.startsWith('@'))
        return toDependency(name);
    const scoped = `@wdio/${name.toLowerCase()}-${type}`;
    const community = `wdio-${name.toLowerCase()}-${type}`;
    const isCommunity = !resolvePackageManifestPath(scoped, dir) && resolvePackageManifestPath(community, dir);
    return toDependency(isCommunity ? community : scoped);
};
const resolveConfig = async (config, options) => {
    const cfg = config?.config;
    if (!cfg)
        return [];
    const toInputs = (plugins, type) => getNames(plugins).map(name => toPluginDependency(name, type, options.configFileDir));
    return [
        ...toInputs([cfg.framework], 'framework'),
        ...toInputs([cfg.runner ?? 'local'], 'runner'),
        ...toInputs(cfg.reporters, 'reporter'),
        ...toInputs(cfg.services, 'service'),
    ];
};
const commands = new Set(['config', 'install', 'repl', 'session']);
const args = {
    binaries: ['wdio'],
    boolean: ['cpuProf', 'headless', 'heapProf'],
    alias: { cpuProf: ['cpu-prof'], heapProf: ['heap-prof'] },
    resolveInputs: parsed => {
        const [command, path] = parsed._;
        const configPath = command === 'run' ? path : command;
        return configPath && !commands.has(configPath) ? [toConfig('webdriver-io', configPath)] : [];
    },
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    args,
};
export default plugin;
