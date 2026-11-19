import { existsSync } from 'node:fs';
import { _glob } from '../../util/glob.js';
import { toEntryPath, toEntry, toDependency } from '../../util/input.js';
import { join, toAbsolute } from '../../util/path.js';
import { hasDependency, load } from '../../util/plugin.js';
import vite from '../vite/index.js';
const title = 'React Router';
const enablers = ['@react-router/dev'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const viteConfig = typeof vite.config === 'function' ? [] : (vite.config ?? []);
const entryExts = ['js', 'jsx', 'ts', 'tsx', 'mjs', 'mts'];
const entryExtsGlob = `{${entryExts.join(',')}}`;
const config = [`react-router.config.${entryExtsGlob}`, ...viteConfig];
const resolveConfig = async (localConfig, options) => {
    const { configFileDir } = options;
    const appDirectory = localConfig.appDirectory ?? 'app';
    const appDir = toAbsolute(appDirectory, configFileDir);
    globalThis.__reactRouterAppDirectory = appDir;
    let routeConfig = [];
    const routesPath = entryExts.map(ext => join(appDir, `routes.${ext}`)).find(existsSync);
    if (routesPath)
        routeConfig = await load(routesPath);
    const mapRoute = (route) => {
        return [toAbsolute(route.file, appDir), ...(route.children ? route.children.flatMap(mapRoute) : [])];
    };
    const routes = routeConfig.flatMap(mapRoute);
    const resolved = [
        toEntry(join(appDir, `routes.${entryExtsGlob}`)),
        toEntry(join(appDir, `root.${entryExtsGlob}`), { production: true }),
        toEntry(join(appDir, `entry.{client,server}.${entryExtsGlob}`), { production: true }),
        ...routes.map(id => toEntryPath(id, { production: true })),
    ];
    const serverEntries = await _glob({
        cwd: appDir,
        patterns: [`entry.server.${entryExtsGlob}`],
    });
    if (serverEntries.length === 0) {
        resolved.push(toDependency('@react-router/node', { production: true }));
        resolved.push(toDependency('isbot', { production: true }));
    }
    return resolved;
};
const note = `Route modules import their types from \`./+types/<route>\`, which \`react-router typegen\` generates.
Run \`react-router typegen\` before Knip (e.g. in CI or a fresh checkout), or these imports are reported as unresolved.`;
export const docs = { note };
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
