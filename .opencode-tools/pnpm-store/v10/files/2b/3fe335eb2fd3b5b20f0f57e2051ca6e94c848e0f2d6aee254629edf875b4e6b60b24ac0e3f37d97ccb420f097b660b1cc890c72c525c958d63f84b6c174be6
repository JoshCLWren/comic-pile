const caches = new WeakMap();
const createEmptyCache = () => ({
    definitions: new Map(),
    usage: new Map(),
    importLookup: new Map(),
    exportedIdentifiers: new Map(),
    exportTables: new Map(),
    generation: 0,
    topologyGeneration: 0,
});
const getCache = (graph) => {
    let cache = caches.get(graph);
    if (!cache) {
        cache = createEmptyCache();
        caches.set(graph, cache);
    }
    return cache;
};
export const getTopologyGeneration = (graph) => getCache(graph).topologyGeneration;
export const invalidateCache = (graph, topologyUnchanged = false) => {
    const cache = caches.get(graph);
    if (cache) {
        cache.definitions.clear();
        cache.usage.clear();
        cache.importLookup.clear();
        cache.exportedIdentifiers.clear();
        cache.exportTables.clear();
        cache.generation++;
        if (!topologyUnchanged)
            cache.topologyGeneration++;
    }
};
export const getCachedDefinition = (graph, filePath, identifier) => {
    const cache = caches.get(graph);
    if (!cache)
        return undefined;
    const fileCache = cache.definitions.get(filePath);
    if (!fileCache)
        return undefined;
    return fileCache.has(identifier) ? fileCache.get(identifier) : undefined;
};
export const setCachedDefinition = (graph, filePath, identifier, result) => {
    const cache = getCache(graph);
    let fileCache = cache.definitions.get(filePath);
    if (!fileCache) {
        fileCache = new Map();
        cache.definitions.set(filePath, fileCache);
    }
    fileCache.set(identifier, result);
};
export const getCachedUsage = (graph, filePath, identifier) => {
    const cache = caches.get(graph);
    if (!cache)
        return undefined;
    const fileCache = cache.usage.get(filePath);
    if (!fileCache)
        return undefined;
    return fileCache.get(identifier);
};
export const setCachedUsage = (graph, filePath, identifier, result) => {
    const cache = getCache(graph);
    let fileCache = cache.usage.get(filePath);
    if (!fileCache) {
        fileCache = new Map();
        cache.usage.set(filePath, fileCache);
    }
    fileCache.set(identifier, result);
};
export const getCachedExportedIdentifiers = (graph, filePath) => {
    const cache = caches.get(graph);
    if (!cache)
        return undefined;
    return cache.exportedIdentifiers.get(filePath);
};
export const setCachedExportedIdentifiers = (graph, filePath, result) => {
    const cache = getCache(graph);
    cache.exportedIdentifiers.set(filePath, result);
};
export const getCachedExportTable = (graph, filePath) => caches.get(graph)?.exportTables.get(filePath);
export const setCachedExportTable = (graph, filePath, table) => {
    getCache(graph).exportTables.set(filePath, table);
};
