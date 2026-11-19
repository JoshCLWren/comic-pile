import fs from 'node:fs';
import path from 'node:path';
import { deserialize, serialize } from 'node:v8';
import { debugLog } from './debug.js';
import { isDirectory, isFile } from './fs.js';
import { timerify } from './Performance.js';
import { isAbsolute, resolve } from './path.js';
const createCache = (filePath) => {
    try {
        return deserialize(fs.readFileSync(filePath));
    }
    catch (_err) {
        debugLog('*', `Error reading cache from ${filePath}`);
    }
};
const create = timerify(createCache);
export class FileEntryCache {
    filePath;
    cache = new Map();
    normalizedEntries = new Map();
    isDirty = false;
    constructor(cacheId, _path) {
        this.filePath = path.resolve(_path, cacheId);
        if (isFile(this.filePath))
            this.cache = create(this.filePath) ?? this.cache;
    }
    getFileDescriptor(filePath) {
        if (!isAbsolute(filePath))
            filePath = resolve(filePath);
        const existing = this.normalizedEntries.get(filePath);
        if (existing)
            return existing;
        let fstat;
        try {
            fstat = fs.statSync(filePath, { throwIfNoEntry: false });
        }
        catch (error) {
            this.removeEntry(filePath);
            return { key: filePath, notFound: true, err: error };
        }
        if (!fstat) {
            this.removeEntry(filePath);
            return { key: filePath, notFound: true };
        }
        let meta = this.cache.get(filePath);
        const cSize = fstat.size;
        const cTime = fstat.mtime.getTime();
        let changed = false;
        if (meta) {
            if (cTime !== meta.mtime || cSize !== meta.size) {
                changed = true;
                meta.data = undefined;
            }
            meta.mtime = cTime;
            meta.size = cSize;
        }
        else {
            changed = true;
            meta = { size: cSize, mtime: cTime };
            this.cache.set(filePath, meta);
        }
        if (changed)
            this.isDirty = true;
        const fd = { key: filePath, changed, meta };
        this.normalizedEntries.set(filePath, fd);
        return fd;
    }
    setFileData(filePath, data) {
        const fd = this.getFileDescriptor(filePath);
        if (!fd.meta)
            return;
        fd.meta.data = data;
        this.isDirty = true;
    }
    removeEntry(entryName) {
        if (!isAbsolute(entryName))
            entryName = resolve(entryName);
        this.normalizedEntries.delete(entryName);
        if (this.cache.delete(entryName))
            this.isDirty = true;
    }
    reconcile() {
        for (const filePath of this.cache.keys()) {
            if (!this.normalizedEntries.has(filePath))
                this.removeEntry(filePath);
        }
        if (!this.isDirty)
            return;
        try {
            const dir = path.dirname(this.filePath);
            if (!isDirectory(dir))
                fs.mkdirSync(dir, { recursive: true });
            fs.writeFileSync(this.filePath, serialize(this.cache));
            this.isDirty = false;
        }
        catch (_err) {
            debugLog('*', `Error writing cache to ${this.filePath}`);
        }
    }
}
