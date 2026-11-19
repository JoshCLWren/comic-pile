import { invalidateCache } from '../graph-explorer/cache.js';
import { getFileTopology, hasSameTopology, isIncrementalFile } from '../session/incremental.js';
import { debugLog } from './debug.js';
import { updateImportMap } from './module-graph.js';
import { toAbsolute, toRelative } from './path.js';
import { clearModuleResolutionCaches } from '../typescript/resolve-module-names.js';
import { clearGlobCache } from './glob-cache.js';
import { clearResolverCache } from './resolve.js';
const createUpdate = (options) => {
    const duration = performance.now() - options.startTime;
    const mem = process.memoryUsage().heapUsed;
    return { duration, mem };
};
export const getSessionHandler = async (options, { analyzedFiles, analyzeSourceFile, subpathReferences, chief, collector, analyze, principal, graph, configurationFiles, isIgnored, unreferencedFiles, entryPaths, }) => {
    const added = new Set();
    const deleted = new Set();
    const modified = new Set();
    if (configurationFiles)
        principal.collectConfigurationImports(configurationFiles);
    const processFileChanges = async (changes) => {
        const startTime = performance.now();
        let hasRelevantChanges = false;
        const configurationChange = configurationFiles?.getChange(changes, options.cwd);
        if (configurationChange)
            throw configurationChange;
        for (const change of changes) {
            const filePath = toAbsolute(change.filePath, options.cwd);
            const relativePath = toRelative(change.filePath, options.cwd);
            if (isIgnored(filePath)) {
                debugLog('*', `ignoring ${change.type} ${relativePath}`);
                continue;
            }
            const workspace = chief.findWorkspaceByFilePath(filePath);
            if (!workspace)
                continue;
            hasRelevantChanges = true;
            switch (change.type) {
                case 'added':
                    principal.addProjectPath(filePath);
                    deleted.delete(filePath);
                    if (principal.projectPaths.has(filePath))
                        added.add(filePath);
                    debugLog(workspace.name, `Watcher: + ${relativePath}`);
                    break;
                case 'deleted':
                    deleted.add(filePath);
                    added.delete(filePath);
                    analyzedFiles.delete(filePath);
                    subpathReferences.release(filePath);
                    principal.removeProjectPath(filePath);
                    debugLog(workspace.name, `Watcher: - ${relativePath}`);
                    break;
                default: {
                    if (!principal.fileManager.hasChanged(filePath)) {
                        debugLog(workspace.name, `Watcher: = ${relativePath}`);
                        continue;
                    }
                    modified.add(filePath);
                    subpathReferences.release(filePath);
                    debugLog(workspace.name, `Watcher: ± ${relativePath}`);
                    break;
                }
            }
            principal.invalidateFile(filePath);
        }
        if (!hasRelevantChanges || (added.size === 0 && deleted.size === 0 && modified.size === 0))
            return;
        let incremental = added.size === 0 && deleted.size === 0;
        if (incremental) {
            for (const filePath of modified) {
                const file = graph.get(filePath);
                if (!file || !analyzedFiles.has(filePath) || !isIncrementalFile(file)) {
                    incremental = false;
                    break;
                }
            }
        }
        if (incremental) {
            for (const filePath of modified) {
                const file = graph.get(filePath);
                if (!file) {
                    incremental = false;
                    break;
                }
                const before = getFileTopology(file);
                await analyzeSourceFile(filePath);
                if (!hasSameTopology(before, file)) {
                    incremental = false;
                    break;
                }
            }
        }
        if (incremental) {
            invalidateCache(graph, true);
            collector.purge();
        }
        else {
            clearResolverCache();
            clearModuleResolutionCaches();
            clearGlobCache();
            invalidateCache(graph);
            subpathReferences.reset();
            const filePaths = await principal.getUsedResolvedFiles((specifier, filePath, importedFilePath) => subpathReferences.add(specifier, filePath, importedFilePath));
            const cachedUnusedFiles = collector.purge();
            for (const filePath of added)
                cachedUnusedFiles.add(filePath);
            for (const filePath of deleted)
                cachedUnusedFiles.delete(filePath);
            if (added.size > 0 || deleted.size > 0) {
                graph.clear();
                for (const filePath of filePaths) {
                    const workspace = chief.findWorkspaceByFilePath(filePath);
                    if (workspace) {
                        await analyzeSourceFile(filePath);
                    }
                }
            }
            else {
                for (const [filePath, file] of graph) {
                    if (filePaths.has(filePath)) {
                        file.importedBy = undefined;
                    }
                    else {
                        graph.delete(filePath);
                        analyzedFiles.delete(filePath);
                        const workspace = chief.findWorkspaceByFilePath(filePath);
                        if (workspace && principal.projectPaths.has(filePath))
                            cachedUnusedFiles.add(filePath);
                    }
                }
                for (const filePath of filePaths) {
                    if (!graph.has(filePath) || !analyzedFiles.has(filePath)) {
                        const workspace = chief.findWorkspaceByFilePath(filePath);
                        if (workspace) {
                            await analyzeSourceFile(filePath);
                        }
                    }
                }
                for (const filePath of modified) {
                    if (!cachedUnusedFiles.has(filePath)) {
                        const workspace = chief.findWorkspaceByFilePath(filePath);
                        if (workspace) {
                            if (principal.projectPaths.has(filePath) || graph.has(filePath)) {
                                await analyzeSourceFile(filePath);
                            }
                        }
                    }
                }
                for (const filePath of filePaths) {
                    const file = graph.get(filePath);
                    if (file?.internalImportCache)
                        updateImportMap(file, file.internalImportCache, graph);
                }
            }
            const unusedFiles = [...cachedUnusedFiles].filter(filePath => !analyzedFiles.has(filePath));
            unreferencedFiles.clear();
            for (const filePath of unusedFiles)
                unreferencedFiles.add(filePath);
        }
        for (const issue of collector.getRetainedIssues())
            collector.addIssue(issue);
        await analyze();
        added.clear();
        deleted.clear();
        modified.clear();
        return createUpdate({ startTime });
    };
    const clearSourceText = () => principal.fileManager.sourceTextCache.clear();
    let pending = Promise.resolve();
    const handleFileChanges = (changes) => {
        const update = pending.then(() => processFileChanges(changes));
        pending = update.then(clearSourceText, clearSourceText);
        return update;
    };
    const getIssues = () => collector.getIssues();
    const getEntryPaths = () => entryPaths;
    const getGraph = () => graph;
    return { handleFileChanges, getEntryPaths, getGraph, getIssues, configurationFiles };
};
