import { readFileSync } from 'node:fs';
import picomatch from 'picomatch';
import { debugLog } from './debug.js';
import { convertGitignoreToPicomatchIgnorePatterns, expandIgnorePatterns } from './parse-and-convert-gitignores.js';
export function parseCodeowners(content) {
    const matchers = content
        .split(/\r?\n/)
        .map(line => line.trim())
        .filter(line => line && !line.startsWith('#'))
        .map(rule => {
        const [path, ...tokens] = rule.split(/\s+/);
        const comment = tokens.findIndex(token => token.startsWith('#'));
        const owners = comment === -1 ? tokens : tokens.slice(0, comment);
        const { pattern } = convertGitignoreToPicomatchIgnorePatterns(path);
        return { owners, match: picomatch(expandIgnorePatterns([pattern], true)) };
    });
    return (filePath) => {
        for (const matcher of matchers.toReversed()) {
            if (matcher.match(filePath)) {
                return matcher.owners;
            }
        }
        return [];
    };
}
export function createOwnershipEngine(filePath) {
    try {
        const content = readFileSync(filePath, 'utf8');
        return parseCodeowners(content);
    }
    catch (error) {
        debugLog('*', `Failed to load codeowners file from ${filePath}`);
        throw error;
    }
}
