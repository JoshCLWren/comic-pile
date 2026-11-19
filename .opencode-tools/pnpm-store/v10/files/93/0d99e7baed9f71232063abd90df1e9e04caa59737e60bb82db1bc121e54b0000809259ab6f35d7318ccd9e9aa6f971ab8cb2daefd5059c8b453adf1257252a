import { Plugins } from './plugins/index.js';
import { perfObserver, timerify } from './util/Performance.js';
const PMap = Plugins;
const timerifyMethods = ['resolve', 'resolveConfig', 'resolveFromAST'];
const PluginEntries = Object.entries(PMap);
if (perfObserver.isTimerifyFunctions) {
    for (const [, plugin] of PluginEntries) {
        for (const method of timerifyMethods) {
            if (method in plugin)
                plugin[method] = timerify(plugin[method], `${method} (${plugin.title})`);
        }
    }
}
const pluginArgsMap = new Map(PluginEntries.flatMap(([pluginName, plugin]) => {
    if (!plugin.args)
        return [];
    const item = [pluginName, plugin.args];
    if (Array.isArray(plugin.args?.binaries))
        return plugin.args.binaries.map(bin => [bin, item]);
    return [[pluginName, item]];
}));
export { PMap as Plugins, PluginEntries, pluginArgsMap };
