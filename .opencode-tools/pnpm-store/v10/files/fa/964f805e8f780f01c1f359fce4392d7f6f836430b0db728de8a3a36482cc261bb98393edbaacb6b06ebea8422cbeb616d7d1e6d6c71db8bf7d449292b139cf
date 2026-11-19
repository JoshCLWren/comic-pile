import { createHash } from 'node:crypto';
import { readdir, readFileSync } from 'node:fs';
import { escapePath, glob as tinyGlob, isDynamicPattern } from 'tinyglobby';
import picomatch from 'picomatch';
import { GLOBAL_IGNORE_PATTERNS } from '../constants.js';
import { compact, partition } from './array.js';
import { debugLogObject } from './debug.js';
import { isDirectory, isFile } from './fs.js';
import { getCachedGitignore, isGitignoreCacheEnabled, setCachedGitignore } from './gitignore-cache.js';
import { timerify } from './Performance.js';
import { expandIgnorePatterns, parseAndConvertGitignorePatterns } from './parse-and-convert-gitignores.js';
import { dirname, isAbsolute, join, relative, toAbsolute, toPosix } from './path.js';
const cachedGitIgnores = new Map();
const cachedGlobIgnores = new Map();
let gitignoreWorkspaceDirs;
const isInNestedWorkspace = (gitignoreDir, dir) => {
    if (!gitignoreWorkspaceDirs)
        return false;
    for (let d = gitignoreDir; d.length > dir.length; d = dirname(d))
        if (gitignoreWorkspaceDirs.has(d))
            return true;
    return false;
};
let gitignoreReconciler;
let gitignoreMatcher = (_filePath) => false;
export const isGitIgnored = (filePath) => gitignoreMatcher(filePath);
let gitignoreFingerprint = '';
export const getGitignoreFingerprint = () => gitignoreFingerprint;
const hashIgnores = (ignores, unignores) => {
    const h = createHash('sha1');
    for (const p of [...ignores].sort()) {
        h.update(p);
        h.update('\0');
    }
    h.update('\u0001');
    for (const p of [...unignores].sort()) {
        h.update(p);
        h.update('\0');
    }
    return h.digest('base64url');
};
const isGitRoot = (dir) => isDirectory(dir, '.git') || isFile(dir, '.git');
const getGitDir = (cwd) => {
    const dotGit = join(cwd, '.git');
    if (isDirectory(dotGit))
        return dotGit;
    if (isFile(dotGit)) {
        const content = readFileSync(dotGit, 'utf8').trim();
        const match = content.match(/^gitdir:\s*(.+)$/);
        if (match)
            return toAbsolute(toPosix(match[1]), cwd);
    }
    return undefined;
};
const findAncestorGitignoreFiles = (cwd) => {
    const gitignorePaths = [];
    if (isGitRoot(cwd))
        return gitignorePaths;
    let dir = dirname(cwd);
    let prev;
    while (dir) {
        const filePath = join(dir, '.gitignore');
        if (isFile(filePath))
            gitignorePaths.push(filePath);
        if (isGitRoot(dir))
            break;
        dir = dirname((prev = dir));
        if (prev === dir || dir === '.')
            break;
    }
    return gitignorePaths;
};
export const findAndParseGitignores = async (cwd, workspaceDirs) => {
    if (isGitignoreCacheEnabled()) {
        const cached = getCachedGitignore(cwd, workspaceDirs);
        if (cached) {
            for (const [dir, data] of cached.perDirIgnores)
                cachedGitIgnores.set(dir, data);
            debugLogObject('*', 'Parsed gitignore files (cached)', { gitignoreFiles: cached.gitignoreFiles });
            return { gitignoreFiles: cached.gitignoreFiles, ignores: cached.ignores, unignores: cached.unignores };
        }
    }
    const ignores = new Set(GLOBAL_IGNORE_PATTERNS);
    const unignores = new Set();
    const gitignoreFiles = [];
    let isIgnored = (_path) => false;
    let isUnignored = (_path) => false;
    const pendingIgnores = Array.from(ignores);
    const pendingUnignores = [];
    const extend = (matcher, pending) => {
        if (pending.length === 0)
            return matcher;
        const incr = picomatch(pending.splice(0));
        return (path) => matcher(path) || incr(path);
    };
    const isExcluded = (path) => {
        isIgnored = extend(isIgnored, pendingIgnores);
        isUnignored = extend(isUnignored, pendingUnignores);
        return isIgnored(path) && !isUnignored(path);
    };
    const seenGitignoreFiles = new Set();
    const addFile = (filePath, baseDir) => {
        const absPath = toPosix(filePath);
        if (seenGitignoreFiles.has(absPath))
            return;
        seenGitignoreFiles.add(absPath);
        gitignoreFiles.push(relative(cwd, filePath));
        const dir = baseDir ?? dirname(absPath);
        const base = relative(cwd, dir);
        const ancestor = base.startsWith('..') ? `${relative(dir, cwd)}/` : undefined;
        const ignoresForDir = new Set(base === '' ? GLOBAL_IGNORE_PATTERNS : []);
        const unignoresForDir = new Set();
        const prevIgnoreSize = ignores.size;
        const patterns = readFileSync(filePath, 'utf8');
        const isRoot = base === '' || base.startsWith('..');
        const escapedBase = escapePath(base);
        for (const { negated, pattern } of parseAndConvertGitignorePatterns(patterns, ancestor)) {
            if (negated) {
                if (isRoot) {
                    if (!unignores.has(pattern)) {
                        unignores.add(pattern);
                        unignoresForDir.add(pattern);
                    }
                }
                else if (!unignores.has(pattern)) {
                    const unignore = join(escapedBase, pattern);
                    unignores.add(unignore);
                    unignoresForDir.add(unignore);
                }
            }
            else if (isRoot) {
                ignores.add(pattern);
                ignoresForDir.add(pattern);
            }
            else if (!unignores.has(pattern)) {
                const ignore = join(escapedBase, pattern);
                ignores.add(ignore);
                ignoresForDir.add(ignore);
            }
        }
        const cacheDir = ancestor ? cwd : dir;
        const cacheForDir = cachedGitIgnores.get(cacheDir);
        if (cacheForDir) {
            for (const pattern of ignoresForDir)
                cacheForDir.ignores.add(pattern);
            for (const pattern of unignoresForDir)
                cacheForDir.unignores.add(pattern);
        }
        else {
            cachedGitIgnores.set(cacheDir, { ignores: ignoresForDir, unignores: unignoresForDir });
        }
        for (const p of unignoresForDir)
            pendingUnignores.push(p);
        if (ignores.size !== prevIgnoreSize) {
            for (const p of ignoresForDir)
                if (!GLOBAL_IGNORE_PATTERNS.includes(p))
                    pendingIgnores.push(p);
        }
    };
    for (const filePath of findAncestorGitignoreFiles(cwd))
        addFile(filePath);
    const gitDir = getGitDir(cwd);
    if (gitDir) {
        const commonDirPath = join(gitDir, 'commondir');
        const commonDir = isFile(commonDirPath)
            ? toAbsolute(toPosix(readFileSync(commonDirPath, 'utf8').trim()), gitDir)
            : gitDir;
        const excludePath = join(commonDir, 'info/exclude');
        if (isFile(excludePath))
            addFile(excludePath, cwd);
    }
    const rootGitignorePath = join(cwd, '.gitignore');
    if (isFile(rootGitignorePath))
        addFile(rootGitignorePath);
    const root = cwd.length > 1 && cwd.endsWith('/') ? cwd.slice(0, -1) : cwd;
    let isRelevantDir;
    if (workspaceDirs && workspaceDirs.size > 0) {
        const relevantAncestors = new Set();
        const nonRootDirs = new Set();
        for (const wsDir of workspaceDirs) {
            if (wsDir !== root)
                nonRootDirs.add(wsDir);
            let dir = wsDir;
            while (dir.length >= root.length) {
                relevantAncestors.add(dir);
                const parent = dirname(dir);
                if (parent === dir)
                    break;
                dir = parent;
            }
        }
        if (nonRootDirs.size > 0) {
            isRelevantDir = (absPath) => {
                if (relevantAncestors.has(absPath))
                    return true;
                for (const wsDir of nonRootDirs)
                    if (absPath.startsWith(`${wsDir}/`))
                        return true;
                return false;
            };
        }
    }
    const rootPrefixLen = root.length + 1;
    await new Promise(resolve => {
        let pending = 0;
        const walk = (dir) => {
            pending++;
            readdir(dir, { withFileTypes: true }, (error, entries) => {
                if (!error) {
                    for (const entry of entries) {
                        if (entry.name === '.gitignore' && (entry.isFile() || entry.isSymbolicLink()))
                            addFile(`${dir}/.gitignore`);
                    }
                    for (const entry of entries) {
                        if (!entry.isDirectory())
                            continue;
                        const absPath = `${dir}/${entry.name}`;
                        if ((isRelevantDir && !isRelevantDir(absPath)) || isExcluded(absPath.slice(rootPrefixLen)))
                            continue;
                        walk(absPath);
                    }
                }
                if (--pending === 0)
                    resolve();
            });
        };
        walk(root);
    });
    if (unignores.size > 0) {
        const unignorePaths = new Set();
        for (const u of unignores) {
            let p = u.replace(/^\*\*\//, '');
            while (p && p !== '.' && p !== '/') {
                unignorePaths.add(p);
                const parent = dirname(p);
                if (parent === p)
                    break;
                p = parent;
            }
        }
        const isShadowed = new Map();
        for (const cacheForDir of cachedGitIgnores.values()) {
            for (const pattern of cacheForDir.ignores) {
                let shadowed = isShadowed.get(pattern);
                if (shadowed === undefined) {
                    const match = picomatch(pattern);
                    shadowed = false;
                    for (const p of unignorePaths) {
                        if (match(p)) {
                            shadowed = true;
                            break;
                        }
                    }
                    isShadowed.set(pattern, shadowed);
                }
                if (shadowed)
                    cacheForDir.ignores.delete(pattern);
            }
        }
    }
    debugLogObject('*', 'Parsed gitignore files', { gitignoreFiles });
    if (isGitignoreCacheEnabled()) {
        setCachedGitignore(cwd, workspaceDirs, gitignoreFiles, ignores, unignores, cachedGitIgnores);
    }
    return { gitignoreFiles, ignores, unignores };
};
const _parseFindGitignores = timerify(findAndParseGitignores);
export async function glob(_patterns, options) {
    if (Array.isArray(_patterns) && _patterns.length === 0)
        return [];
    const cachedIgnores = options.gitignore ? cachedGlobIgnores.get(options.dir) : undefined;
    const _ignore = [...GLOBAL_IGNORE_PATTERNS];
    const [negatedPatterns, patterns] = partition(_patterns, pattern => pattern.startsWith('!'));
    if (!cachedIgnores && options.gitignore && options.label) {
        let dir = options.dir;
        let prev;
        while (dir) {
            const cacheForDir = cachedGitIgnores.get(dir);
            if (cacheForDir)
                _ignore.push(...cacheForDir.ignores);
            dir = dirname((prev = dir));
            if (prev === dir || dir === '.')
                break;
        }
        if (!gitignoreReconciler) {
            const prefix = `${options.dir}/`;
            for (const [gitignoreDir, cacheForDir] of cachedGitIgnores) {
                if (gitignoreDir.startsWith(prefix) && !isInNestedWorkspace(gitignoreDir, options.dir)) {
                    _ignore.push(...cacheForDir.ignores);
                }
            }
        }
        cachedGlobIgnores.set(options.dir, compact(_ignore));
    }
    const ignores = cachedIgnores ?? _ignore;
    const isStatic = options.gitignore && !patterns.some(pattern => isDynamicPattern(pattern));
    const ignorePatterns = (isStatic ? expandIgnorePatterns(ignores) : ignores).concat(negatedPatterns.map(pattern => pattern.slice(1)));
    const { dir, label, ...fgOptions } = {
        ...options,
        ignore: ignorePatterns,
        expandDirectories: false,
        followSymbolicLinks: false,
    };
    const paths = await tinyGlob(patterns, fgOptions);
    debugLogObject(relative(options.cwd, dir), label ? `Finding ${label}` : 'Finding paths', () => ({
        patterns,
        ...fgOptions,
        ignore: cachedIgnores && negatedPatterns.length === 0
            ? `// using cache from previous glob cwd: ${fgOptions.cwd}`
            : ignorePatterns,
        paths,
    }));
    return paths;
}
export function reconcileGitignoredPaths(paths, cwd) {
    if (!gitignoreReconciler || paths.length === 0)
        return paths;
    const isGitIgnored = gitignoreReconciler;
    const result = [];
    for (const path of paths)
        if (!isGitIgnored(isAbsolute(path) ? path : join(cwd, path)))
            result.push(path);
    return result;
}
export async function getGitIgnoredHandler(options, workspaceDirs) {
    cachedGitIgnores.clear();
    cachedGlobIgnores.clear();
    gitignoreWorkspaceDirs = workspaceDirs;
    gitignoreReconciler = undefined;
    gitignoreMatcher = () => false;
    gitignoreFingerprint = '';
    if (options.gitignore === false)
        return () => false;
    const { ignores, unignores } = await _parseFindGitignores(options.cwd, workspaceDirs);
    gitignoreFingerprint = hashIgnores(ignores, unignores);
    const ignoreMatcher = picomatch(expandIgnorePatterns(ignores));
    const unignoreMatcher = unignores.size > 0 ? picomatch(expandIgnorePatterns(unignores)) : undefined;
    const matcher = unignoreMatcher ? (path) => ignoreMatcher(path) && !unignoreMatcher(path) : ignoreMatcher;
    const cache = new Map();
    const isGitIgnored = (filePath) => {
        let result = cache.get(filePath);
        if (result === undefined) {
            result = matcher(relative(options.cwd, filePath));
            cache.set(filePath, result);
        }
        return result;
    };
    gitignoreMatcher = isGitIgnored;
    if (unignores.size > 0)
        gitignoreReconciler = isGitIgnored;
    return isGitIgnored;
}
