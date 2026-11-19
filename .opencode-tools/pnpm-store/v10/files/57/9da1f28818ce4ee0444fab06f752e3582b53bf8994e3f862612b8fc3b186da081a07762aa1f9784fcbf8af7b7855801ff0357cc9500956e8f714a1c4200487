import { IMPORT_STAR } from '../../constants.js';
import { compareStrings } from '../../util/string.js';
import { createExportResolver } from './resolve-export-origins.js';
const SEVERITY = { ambiguous: 3, shadowed: 2, converged: 1 };
export const getContention = (graph, filePath) => {
    const result = new Map();
    const node = graph.get(filePath);
    if (!node)
        return result;
    const nodes = new Map([[filePath, node]]);
    const getNode = (path) => {
        if (nodes.has(path))
            return nodes.get(path);
        const found = graph.get(path);
        nodes.set(path, found);
        return found;
    };
    const positions = new Map();
    const resolver = createExportResolver(graph);
    const findOriginExport = (origin) => {
        if (origin.identifier === IMPORT_STAR)
            return;
        const originNode = getNode(origin.filePath);
        if (!originNode)
            return;
        const exact = originNode.exports.get(origin.identifier);
        if (exact?.binding === origin.identifier)
            return exact;
        let nearest;
        for (const _export of originNode.exports.values()) {
            if (_export.binding !== origin.identifier)
                continue;
            if (!nearest || _export.pos < nearest.pos)
                nearest = _export;
        }
        return nearest;
    };
    const locateOrigin = (origin) => {
        const key = `${origin.filePath}:${origin.identifier}`;
        const cached = positions.get(key);
        if (cached)
            return cached;
        const _export = findOriginExport(origin);
        const located = _export ? { ...origin, line: _export.line, col: _export.col } : { ...origin };
        positions.set(key, located);
        return located;
    };
    const materialize = (sitePath, identifier, entry, kind) => {
        const isShadowed = kind === 'shadowed';
        const origins = [];
        for (const origin of (isShadowed && entry.shadowed ? entry.shadowed : entry.origins).values())
            origins.push(locateOrigin(origin));
        origins.sort((a, b) => compareStrings(a.filePath, b.filePath) || compareStrings(a.identifier, b.identifier));
        const site = {
            kind,
            filePath: sitePath,
            identifier,
            origins,
            sources: [...(isShadowed ? (entry.shadowedSources ?? []) : entry.sources.keys())],
        };
        const _export = getNode(sitePath)?.exports.get(identifier);
        if (_export) {
            site.line = _export.line;
            site.col = _export.col;
        }
        if (isShadowed) {
            const [winner] = entry.origins.values();
            if (winner)
                site.winner = locateOrigin(winner);
        }
        return site;
    };
    const compareSites = (describedIdentifier) => (a, b) => {
        const isOwnA = a.filePath === filePath && a.identifier === describedIdentifier;
        const isOwnB = b.filePath === filePath && b.identifier === describedIdentifier;
        if (isOwnA !== isOwnB)
            return isOwnA ? -1 : 1;
        return (SEVERITY[b.kind] - SEVERITY[a.kind] ||
            compareStrings(a.filePath, b.filePath) ||
            compareStrings(a.identifier, b.identifier));
    };
    const sitesByFile = new Map();
    const inspect = (sitePath, identifier) => {
        let sites = sitesByFile.get(sitePath);
        if (!sites)
            sitesByFile.set(sitePath, (sites = new Map()));
        if (identifier !== undefined && (sitePath === filePath || sites.has(identifier)))
            return sites.get(identifier);
        const info = resolver.getInfo(sitePath);
        const table = identifier === undefined ? resolver.getTable(sitePath) : new Map();
        if (identifier !== undefined) {
            const entry = resolver.resolve(sitePath, identifier);
            if (entry)
                table.set(identifier, entry);
        }
        const entries = new Map();
        const firstSources = new Map();
        const addEntry = (name, resolution) => {
            const entry = {
                ...resolution,
                sources: new Map(),
                shadowed: undefined,
                shadowedSources: undefined,
            };
            const first = firstSources.get(name);
            if (first)
                entry.sources.set(first.filePath, first);
            entries.set(name, entry);
            return entry;
        };
        for (const [name, entry] of table) {
            if (entry.origins.size >= 2)
                addEntry(name, entry);
        }
        const contribute = (name, source, origins, isStar) => {
            const resolution = table.get(name);
            if (!resolution || origins.size === 0)
                return;
            let entry = entries.get(name);
            let contributes = false;
            if (isStar && resolution.hasExplicitExport) {
                for (const [key, origin] of origins) {
                    if (resolution.origins.has(key))
                        contributes = true;
                    else {
                        entry ??= addEntry(name, resolution);
                        (entry.shadowed ??= new Map()).set(key, origin);
                        (entry.shadowedSources ??= new Set()).add(source.filePath);
                    }
                }
            }
            else
                contributes = true;
            if (!contributes)
                return;
            const first = firstSources.get(name);
            if (!entry && first && first.filePath !== source.filePath)
                entry = addEntry(name, resolution);
            if (entry)
                entry.sources.set(source.filePath, source);
            else
                firstSources.set(name, source);
        };
        for (const [name, sources] of info.references) {
            if (!table.has(name))
                continue;
            for (const source of sources) {
                const entry = resolver.resolve(source.filePath, source.identifier);
                if (entry)
                    contribute(name, source, entry.origins, false);
            }
        }
        for (const [name, origins] of info.terminals) {
            const entry = table.get(name);
            if (!entry)
                continue;
            for (const origin of origins) {
                if (origin.identifier === IMPORT_STAR && graph.has(origin.filePath))
                    contribute(name, origin, entry.origins, false);
            }
        }
        for (const sourcePath of info.stars) {
            if (identifier === undefined) {
                for (const [name, entry] of resolver.getTable(sourcePath)) {
                    if (name !== 'default')
                        contribute(name, { filePath: sourcePath, identifier: name }, entry.origins, true);
                }
            }
            else if (identifier !== 'default') {
                const entry = resolver.resolve(sourcePath, identifier);
                if (entry)
                    contribute(identifier, { filePath: sourcePath, identifier }, entry.origins, true);
            }
        }
        for (const [name, entry] of entries) {
            let kind;
            if (entry.origins.size >= 2)
                kind = 'ambiguous';
            else if (entry.shadowed?.size)
                kind = 'shadowed';
            else if (entry.sources.size >= 2) {
                const [origin] = entry.origins.values();
                if (origin) {
                    for (const [path, source] of entry.sources) {
                        if (!resolver.reachesOrigin(source, origin, { filePath: sitePath, identifier: name }))
                            entry.sources.delete(path);
                    }
                    if (entry.sources.size >= 2)
                        kind = 'converged';
                }
            }
            sites.set(name, kind ? materialize(sitePath, name, entry, kind) : undefined);
        }
        if (identifier !== undefined) {
            if (!sites.has(identifier))
                sites.set(identifier, undefined);
            return sites.get(identifier);
        }
    };
    inspect(filePath);
    for (const [identifier, entry] of resolver.getTable(filePath)) {
        if (identifier === 'default')
            continue;
        const sites = [];
        const ownSite = inspect(filePath, identifier);
        if (ownSite)
            sites.push(ownSite);
        else if (!node.importedBy?.reExport.size && !node.importedBy?.reExportAs.size)
            continue;
        const origins = entry.origins;
        const visited = new Set([`${filePath}\0${identifier}`]);
        const queue = [[filePath, identifier]];
        const visitConsumer = (consumerPath, consumerId) => {
            const key = `${consumerPath}\0${consumerId}`;
            if (visited.has(key))
                return;
            visited.add(key);
            const consumerEntry = resolver.resolve(consumerPath, consumerId);
            if (!consumerEntry)
                return;
            const site = inspect(consumerPath, consumerId);
            if (site)
                sites.push(site);
            if (site?.kind === 'ambiguous')
                return;
            for (const origin of consumerEntry.origins.keys()) {
                if (origins.has(origin)) {
                    queue.push([consumerPath, consumerId]);
                    return;
                }
            }
        };
        for (let index = 0; index < queue.length; index++) {
            const [currentPath, currentId] = queue[index];
            const importedBy = getNode(currentPath)?.importedBy;
            if (!importedBy)
                continue;
            const consumers = importedBy.reExport.get(currentId);
            if (consumers)
                for (const consumerPath of consumers)
                    visitConsumer(consumerPath, currentId);
            const aliases = importedBy.reExportAs.get(currentId);
            if (aliases) {
                for (const [alias, consumerPaths] of aliases) {
                    for (const consumerPath of consumerPaths)
                        visitConsumer(consumerPath, alias);
                }
            }
            const starConsumers = importedBy.reExport.get(IMPORT_STAR);
            if (starConsumers)
                for (const consumerPath of starConsumers)
                    visitConsumer(consumerPath, currentId);
        }
        if (sites.length === 0)
            continue;
        sites.sort(compareSites(identifier));
        const branching = new Set();
        const conflict = new Set();
        for (const site of sites) {
            if (site.kind === 'converged')
                branching.add(site.filePath);
            else {
                let hasGraphOrigin = false;
                for (const origin of site.origins) {
                    if (!graph.has(origin.filePath))
                        continue;
                    conflict.add(origin.filePath);
                    hasGraphOrigin = true;
                }
                if (site.winner && graph.has(site.winner.filePath)) {
                    conflict.add(site.winner.filePath);
                    hasGraphOrigin = true;
                }
                if (!hasGraphOrigin)
                    conflict.add(site.filePath);
            }
        }
        result.set(identifier, {
            branching: [...branching].sort(),
            conflict: [...conflict].sort(),
            sites,
        });
    }
    return new Map([...result].sort(([a], [b]) => compareStrings(a, b)));
};
