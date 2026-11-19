import { readFileSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { toModule, toEntryPath, toDependency } from '../../util/input.js';
import { isDirectory, isFile, tryRealpath } from '../../util/fs.js';
import { getPackageNameFromModuleSpecifier } from '../../util/modules.js';
import { dirname, isInternal, join, toAbsolute } from '../../util/path.js';
import { isGitIgnored } from '../../util/glob-core.js';
import { debugLog } from '../../util/debug.js';
import { hasUrlScheme } from '../../util/url.js';
import { parseVarlockFile } from './parse.js';
const resolvePath = (path, cwd) => path.startsWith('~/') ? join(homedir(), path.slice(2)) : toAbsolute(path, cwd);
const isExternalUrl = (path) => path.startsWith('//') || hasUrlScheme(path);
const isLocalPath = (path) => path.startsWith('~/') || isInternal(path);
const expandLoadPath = (path) => {
    if (!isDirectory(path))
        return [path];
    try {
        const paths = [];
        for (const name of readdirSync(path))
            if (name === '.env' || name.startsWith('.env.'))
                paths.push(join(path, name));
        return paths;
    }
    catch {
        return [];
    }
};
export const scanVarlockFiles = (paths, cwd) => {
    const inputs = [];
    const queue = [];
    for (const path of paths)
        queue.push(...expandLoadPath(resolvePath(path, cwd)));
    const visited = new Set();
    for (const path of queue) {
        if (!isFile(path) || isGitIgnored(path))
            continue;
        const realPath = tryRealpath(path);
        if (visited.has(realPath))
            continue;
        visited.add(realPath);
        let source;
        try {
            source = readFileSync(realPath, 'utf8');
        }
        catch (error) {
            debugLog('Varlock', `Unable to read ${realPath} (${error instanceof Error ? error.message : error})`);
            continue;
        }
        const { directives, disabled } = parseVarlockFile(source);
        if (disabled)
            continue;
        for (const { name, descriptor, enabled, allowMissing } of directives) {
            if (!descriptor || descriptor.includes('$') || isExternalUrl(descriptor) || enabled === false)
                continue;
            if (name === 'plugin') {
                if (isLocalPath(descriptor)) {
                    inputs.push(toEntryPath(descriptor.startsWith('~/') ? resolvePath(descriptor, dirname(realPath)) : descriptor, {
                        production: true,
                        containingFilePath: realPath,
                    }));
                }
                else {
                    const packageName = getPackageNameFromModuleSpecifier(descriptor);
                    if (packageName) {
                        inputs.push(toDependency(packageName, { containingFilePath: realPath, production: true }));
                    }
                }
                continue;
            }
            if (!isLocalPath(descriptor))
                continue;
            const importPath = resolvePath(descriptor, dirname(realPath));
            if (isFile(importPath) || isDirectory(importPath))
                queue.push(...expandLoadPath(importPath));
            else if (allowMissing !== true && allowMissing !== null && enabled !== null) {
                inputs.push(toModule(descriptor, { containingFilePath: realPath }));
            }
        }
    }
    return inputs;
};
