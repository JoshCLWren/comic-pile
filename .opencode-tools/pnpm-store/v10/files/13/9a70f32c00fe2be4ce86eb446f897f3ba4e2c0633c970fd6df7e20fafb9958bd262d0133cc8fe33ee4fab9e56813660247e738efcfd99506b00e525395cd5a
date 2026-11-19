import { globSync } from 'tinyglobby';
import { compact } from './array.js';
import { computeGlobCacheKey, createDirTracker, getCachedGlob, isGlobCacheEnabled, setCachedGlob, } from './glob-cache.js';
import { getGitignoreFingerprint, glob, reconcileGitignoredPaths } from './glob-core.js';
import { timerify } from './Performance.js';
import { isAbsolute, join, relative } from './path.js';
const prepend = (pattern, cwd, relativePath) => {
    const isNegated = pattern.startsWith('!');
    const id = isNegated ? pattern.slice(1) : pattern;
    if (id && !isAbsolute(id) && !relativePath)
        return pattern;
    const globPattern = isAbsolute(id) ? relative(cwd, id) : join(relativePath, id);
    return isNegated ? `!${globPattern}` : globPattern;
};
const prependDirToPatterns = (cwd, dir, patterns) => {
    const relativePath = dir === cwd ? '' : relative(cwd, dir);
    return compact(patterns.map(p => removeProductionSuffix(prepend(p, cwd, relativePath)))).sort(negatedLast);
};
export const removeProductionSuffix = (pattern) => pattern.replace(/!$/, '');
const negatedLast = (pattern) => (pattern.startsWith('!') ? 1 : -1);
export const prependDirToPattern = (dir, pattern) => {
    if (pattern.startsWith('!'))
        return `!${join(dir, pattern.slice(1))}`;
    return join(dir, pattern);
};
export const rebasePattern = (pattern, base, dir) => {
    const isNegated = pattern.startsWith('!');
    const id = isNegated ? pattern.slice(1) : pattern;
    const rebased = relative(dir, isAbsolute(id) ? id : join(base, id));
    return isNegated ? `!${rebased}` : rebased;
};
export const negate = (pattern) => pattern.replace(/^!?/, '!');
export const hasProductionSuffix = (pattern) => pattern.endsWith('!');
export const hasNoProductionSuffix = (pattern) => !pattern.endsWith('!');
const defaultGlob = async ({ cwd, dir = cwd, patterns, gitignore = true, label }) => {
    if (patterns.length === 0)
        return [];
    const globPatterns = prependDirToPatterns(cwd, dir, patterns);
    if (globPatterns[0].startsWith('!'))
        return [];
    const cacheEnabled = isGlobCacheEnabled();
    const gitignoreFingerprint = gitignore ? getGitignoreFingerprint() : '';
    const cacheKey = cacheEnabled
        ? computeGlobCacheKey({ patterns: globPatterns, cwd, dir, gitignore, gitignoreFingerprint })
        : '';
    if (cacheEnabled) {
        const cached = getCachedGlob(cacheKey);
        if (cached)
            return gitignore ? reconcileGitignoredPaths(cached, cwd) : cached;
    }
    const tracker = cacheEnabled ? createDirTracker() : undefined;
    const paths = await glob(globPatterns, {
        cwd,
        dir,
        gitignore,
        absolute: true,
        dot: true,
        label,
        fs: tracker?.fs,
    });
    if (cacheEnabled && paths.length > 0)
        setCachedGlob(cacheKey, paths, dir, tracker?.dirs);
    return gitignore ? reconcileGitignoredPaths(paths, cwd) : paths;
};
const syncGlob = ({ cwd, patterns }) => {
    const cacheEnabled = isGlobCacheEnabled();
    const patternList = [patterns].flat().map(pattern => prepend(pattern, cwd, ''));
    const cacheKey = cacheEnabled
        ? computeGlobCacheKey({ patterns: patternList, cwd, dir: cwd, gitignore: false, gitignoreFingerprint: '' })
        : '';
    if (cacheEnabled) {
        const cached = getCachedGlob(cacheKey);
        if (cached)
            return cached;
    }
    const tracker = cacheEnabled ? createDirTracker() : undefined;
    const paths = globSync(patternList, {
        cwd,
        absolute: true,
        followSymbolicLinks: false,
        expandDirectories: false,
        fs: tracker?.fs,
    });
    if (cacheEnabled && paths.length > 0)
        setCachedGlob(cacheKey, paths, cwd, tracker?.dirs);
    return paths;
};
const dirGlob = async ({ cwd, patterns, gitignore = true }) => glob(patterns.map(pattern => prepend(pattern, cwd, '')), { cwd, dir: cwd, onlyDirectories: true, gitignore });
export const _glob = timerify(defaultGlob);
export const _syncGlob = timerify(syncGlob);
export const _dirGlob = timerify(dirGlob);
