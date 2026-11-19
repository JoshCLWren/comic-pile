import { isFile, loadJSON } from '../../util/fs.js';
import { toDependency } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
import { resolvePackageManifestPath } from '../../util/resolve.js';
const title = 'Capacitor';
const enablers = [/^@capacitor\//];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['capacitor.config.{json,js,ts}'];
const resolveConfig = async (config, { configFileDir, cwd, manifest }) => {
    const platforms = [];
    if (isFile(configFileDir, 'android/capacitor.settings.gradle'))
        platforms.push('android');
    const hasIOS = isFile(configFileDir, 'ios/App/Podfile') || isFile(configFileDir, 'ios/App/CapApp-SPM/Package.swift');
    if (hasIOS)
        platforms.push('ios');
    const plugins = new Set(platforms.length ? [] : config.includePlugins);
    const automatic = [];
    for (const platform of platforms) {
        const included = config[platform]?.includePlugins ?? config.includePlugins;
        if (included) {
            for (const name of included)
                plugins.add(name);
        }
        else {
            automatic.push(platform);
        }
    }
    if (automatic.length) {
        for (const dependencies of [manifest.dependencies, manifest.devDependencies]) {
            for (const name in dependencies) {
                const path = resolvePackageManifestPath(name, cwd);
                if (!path)
                    continue;
                const pkg = await loadJSON(path);
                if (automatic.some(platform => pkg.capacitor?.[platform]))
                    plugins.add(name);
            }
        }
    }
    return [...plugins, ...platforms.map(platform => `@capacitor/${platform}`)].map(id => toDependency(id, { production: true }));
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
