import { basename, dirname } from '../util/path.js';
import { hasUrlScheme } from '../util/url.js';
const isAlias = (s) => (s.charCodeAt(0) === 64 && s.charCodeAt(1) === 47) || s.charCodeAt(0) === 126 || s.charCodeAt(0) === 35;
export const isScopedPackage = (s) => s.charCodeAt(0) === 64 && s.charCodeAt(1) !== 47;
export const isTildePackage = (s) => s.charCodeAt(0) === 126 && s.charCodeAt(1) !== 47;
export const getUrlSpecifier = (url) => {
    if (!url ||
        url.startsWith('//') ||
        url.startsWith('/') ||
        url.startsWith('#') ||
        hasUrlScheme(url) ||
        url.includes('$') ||
        url.includes('#{') ||
        url.includes('('))
        return;
    let end = url.length;
    const queryIndex = url.indexOf('?');
    if (queryIndex !== -1)
        end = queryIndex;
    const fragmentIndex = url.indexOf('#');
    if (fragmentIndex !== -1 && fragmentIndex < end)
        end = fragmentIndex;
    const path = url.slice(0, end);
    if (!path)
        return;
    return isScopedPackage(path) ? path : ensureRelative(path);
};
const ensureRelative = (spec) => (spec.startsWith('.') || isAlias(spec) ? spec : `./${spec}`);
export const splitSpec = (specifier) => {
    const spec = ensureRelative(specifier);
    return { dir: dirname(spec), name: basename(spec) };
};
