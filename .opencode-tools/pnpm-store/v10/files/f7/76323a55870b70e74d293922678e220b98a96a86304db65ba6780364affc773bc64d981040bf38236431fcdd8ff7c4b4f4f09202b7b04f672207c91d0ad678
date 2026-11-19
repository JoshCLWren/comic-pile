import { toDependency, toEntryPath } from '../../util/input.js';
import { isAbsolute, toAbsolute } from '../../util/path.js';
import { findWebpackDependenciesFromConfig } from '../webpack/index.js';
const isLocalPath = (name) => name.startsWith('.') || isAbsolute(name);
const FIRST_PARTY_MODULES = new Set([
    'content-docs',
    'content-blog',
    'content-pages',
    'debug',
    'sitemap',
    'svgr',
    'rsdoctor',
    'pwa',
    'client-redirects',
    'ideal-image',
    'google-analytics',
    'google-gtag',
    'google-tag-manager',
    'classic',
    'live-codeblock',
    'search-algolia',
    'mermaid',
]);
export const CORE_CLIENT_API = [
    'BrowserOnly',
    'ComponentCreator',
    'constants',
    'ExecutionEnvironment',
    'Head',
    'Interpolate',
    'isInternalUrl',
    'Link',
    'Noop',
    'renderRoutes',
    'router',
    'Translate',
    'useBaseUrl',
    'useBrokenLinks',
    'useDocusaurusContext',
    'useGlobalData',
    'useIsBrowser',
    'useIsomorphicLayoutEffect',
    'useRouteContext',
];
const resolveModuleName = (name, type) => {
    if (name.includes(`${type}-`))
        return name;
    if (!name.startsWith('@')) {
        const prefix = FIRST_PARTY_MODULES.has(name) ? '@docusaurus/' : 'docusaurus-';
        return `${prefix}${type}-${name}`;
    }
    const [scope, ...rest] = name.split('/');
    const baseName = rest.length ? `-${rest.join('/')}` : '';
    return `${scope}/docusaurus-${type}${baseName}`;
};
const resolveSidebarPath = (config) => {
    const path = config?.sidebarPath ?? config?.docs?.sidebarPath;
    return typeof path === 'string' ? path : undefined;
};
const resolveArrayConfig = ([name, config], type, cwd) => {
    if (typeof name !== 'string')
        return [];
    const sidebarPath = type !== 'theme' ? resolveSidebarPath(config) : undefined;
    const sidebar = sidebarPath ? [toEntryPath(sidebarPath, { production: true, dir: cwd })] : [];
    if (isLocalPath(name))
        return [toEntryPath(toAbsolute(name, cwd), { production: true }), ...sidebar];
    return [toDependency(resolveModuleName(name, type), { production: type !== 'plugin' }), ...sidebar];
};
export const resolveConfigItems = async (items, type, options) => {
    const inputs = new Set();
    for (let item of items) {
        if (typeof item === 'function')
            item = item();
        if (!item)
            continue;
        if (typeof item === 'string') {
            if (isLocalPath(item))
                inputs.add(toEntryPath(toAbsolute(item, options.cwd), { production: true }));
            else
                inputs.add(toDependency(resolveModuleName(item, type), { production: type !== 'plugin' }));
        }
        else if (Array.isArray(item)) {
            for (const input of resolveArrayConfig(item, type, options.cwd))
                inputs.add(input);
        }
        else if (typeof item.configureWebpack === 'function') {
            const utils = { getStyleLoaders: () => [], getJSLoader: () => null };
            const config = item.configureWebpack({}, false, utils);
            for (const input of await findWebpackDependenciesFromConfig(config, options))
                inputs.add(input);
        }
        else if (typeof item.configurePostCss === 'function') {
        }
    }
    return inputs;
};
