import { getTopologyGeneration, invalidateCache as invalidateCacheInternal } from './cache.js';
import { buildExportsTree } from './operations/build-exports-tree.js';
import { findAllCycles } from './operations/find-all-cycles.js';
import { findCycles } from './operations/find-cycles.js';
import { getContention } from './operations/get-contention.js';
import { getDependencyUsage } from './operations/get-dependency-usage.js';
import { getUsage } from './operations/get-usage.js';
import { hasStrictlyNsReferences } from './operations/has-strictly-ns-references.js';
import { isEnumerated } from './operations/is-enumerated.js';
import { isReferenced } from './operations/is-referenced.js';
import { resolveDefinition } from './operations/resolve-definition.js';
import { resolveExportOrigins } from './operations/resolve-export-origins.js';
export const createGraphExplorer = (graph, entryPaths, cacheUsage = false) => {
    const references = new Map();
    let generation = getTopologyGeneration(graph);
    const reference = (filePath, identifier, options) => {
        if (!cacheUsage)
            return isReferenced(graph, entryPaths, filePath, identifier, options);
        const current = getTopologyGeneration(graph);
        if (current !== generation) {
            references.clear();
            generation = current;
        }
        let file = references.get(filePath);
        if (!file)
            references.set(filePath, (file = new Map()));
        const key = `${options.traverseEntries ? 1 : 0}${options.treatStarAtEntryAsReferenced ? 1 : 0}:${identifier}`;
        const cached = file.get(key);
        if (cached)
            return cached;
        const result = isReferenced(graph, entryPaths, filePath, identifier, options);
        file.set(key, result);
        return result;
    };
    return {
        isReferenced: reference,
        hasStrictlyNsReferences: (filePath, identifier) => hasStrictlyNsReferences(graph, filePath, graph.get(filePath)?.importedBy, identifier),
        isEnumerated: (filePath, identifier) => isEnumerated(graph, filePath, graph.get(filePath)?.importedBy, identifier),
        buildExportsTree: (options) => buildExportsTree(graph, entryPaths, options),
        resolveExportOrigins: (filePath, identifier) => resolveExportOrigins(graph, filePath, identifier),
        getDependencyUsage: (pattern) => getDependencyUsage(graph, pattern),
        resolveDefinition: (filePath, identifier) => resolveDefinition(graph, filePath, identifier),
        getUsage: (filePath, identifier) => getUsage(graph, entryPaths, filePath, identifier),
        findCycles: (filePath, maxDepth) => findCycles(graph, filePath, maxDepth),
        findAllCycles: (ignoredFlags) => findAllCycles(graph, ignoredFlags),
        getContention: (filePath) => getContention(graph, filePath),
        invalidateCache: () => invalidateCacheInternal(graph),
    };
};
