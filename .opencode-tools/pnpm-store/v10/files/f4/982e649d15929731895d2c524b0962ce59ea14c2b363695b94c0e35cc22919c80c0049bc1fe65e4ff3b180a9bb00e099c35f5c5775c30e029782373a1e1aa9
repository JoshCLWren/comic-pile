import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { FOREIGN_FILE_EXTENSIONS } from '../constants.js';
import { debugLog } from '../util/debug.js';
import { CompilerError, ConfigurationError } from '../util/errors.js';
import { extname, isInternal } from '../util/path.js';
export class SourceFileManager {
    sourceTextCache = new Map();
    compilers;
    rawContentHashes = new Map();
    isSession;
    constructor({ compilers, isSession = false }) {
        this.compilers = compilers;
        this.isSession = isSession;
    }
    loadSourceText(filePath) {
        const cachedSourceText = this.sourceTextCache.get(filePath);
        if (cachedSourceText !== undefined)
            return cachedSourceText;
        const ext = extname(filePath);
        const compiler = this.compilers.get(ext);
        if (FOREIGN_FILE_EXTENSIONS.has(ext) && !compiler) {
            this.sourceTextCache.set(filePath, '');
            return '';
        }
        const contents = this.readRawFile(filePath);
        if (contents === undefined) {
            if (isInternal(filePath))
                debugLog('*', `Unable to read ${filePath}`);
            this.sourceTextCache.set(filePath, '');
            return '';
        }
        if (!compiler)
            return this.cacheSourceText(filePath, contents, contents);
        let result;
        try {
            result = compiler(contents, filePath);
            if (result !== null && (typeof result === 'object' || typeof result === 'function')) {
                const pending = Promise.resolve(result).then(result => {
                    const isCurrent = this.sourceTextCache.get(filePath) === pending;
                    if (isCurrent)
                        this.sourceTextCache.delete(filePath);
                    const sourceText = this.validateCompilerResult(result, filePath, ext);
                    if (isCurrent)
                        this.cacheSourceText(filePath, sourceText, contents);
                    debugLog('*', `Compiled ${filePath}`);
                    return sourceText;
                }, cause => {
                    if (this.sourceTextCache.get(filePath) === pending)
                        this.sourceTextCache.delete(filePath);
                    throw new CompilerError(`Compiler for ${ext} failed (${filePath})`, { cause });
                });
                this.sourceTextCache.set(filePath, pending);
                return pending;
            }
        }
        catch (cause) {
            throw new CompilerError(`Compiler for ${ext} failed (${filePath})`, { cause });
        }
        const sourceText = this.validateCompilerResult(result, filePath, ext);
        debugLog('*', `Compiled ${filePath}`);
        return this.cacheSourceText(filePath, sourceText, contents);
    }
    invalidate(filePath) {
        this.sourceTextCache.delete(filePath);
        this.rawContentHashes.delete(filePath);
    }
    hasChanged(filePath) {
        const previousHash = this.rawContentHashes.get(filePath);
        if (previousHash === undefined)
            return true;
        const contents = this.readRawFile(filePath);
        return contents === undefined || createHash('sha1').update(contents).digest('hex') !== previousHash;
    }
    readRawFile(filePath) {
        try {
            return readFileSync(filePath, 'utf8');
        }
        catch {
            return undefined;
        }
    }
    cacheSourceText(filePath, sourceText, contents) {
        this.sourceTextCache.set(filePath, sourceText);
        if (this.isSession)
            this.rawContentHashes.set(filePath, createHash('sha1').update(contents).digest('hex'));
        return sourceText;
    }
    validateCompilerResult(result, filePath, ext) {
        if (typeof result === 'string')
            return result;
        const category = result === null ? 'null' : typeof result;
        throw new ConfigurationError(`Compiler for ${ext} returned ${category} for ${filePath}; expected a string or PromiseLike<string>`);
    }
}
