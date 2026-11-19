import { extractSpecifiers } from './typescript/follow-imports.js';
import { _parseFile } from './typescript/ast-nodes.js';
import { CacheConsultant } from './CacheConsultant.js';
import { DEFAULT_EXTENSIONS } from './constants.js';
import { _getImportsAndExports } from './typescript/get-imports-and-exports.js';
import { createBunShellVisitor } from './typescript/visitors/script-visitors.js';
import { buildVisitor } from './typescript/visitors/walk.js';
import { createCustomModuleResolver, createGlobAliasResolver } from './typescript/resolve-module-names.js';
import { SourceFileManager } from './typescript/SourceFileManager.js';
import { compact } from './util/array.js';
import { debugLog } from './util/debug.js';
import { getSubpathImport } from './util/modules.js';
import { timerify } from './util/Performance.js';
import { extname, isInNodeModules, toAbsolute } from './util/path.js';
const copyFileNode = (file) => ({
    ...file,
    imports: {
        ...file.imports,
        external: new Set(file.imports.external),
        externalRefs: new Set(file.imports.externalRefs),
    },
});
const tryParseFile = (filePath, sourceText) => {
    try {
        return _parseFile(filePath, sourceText);
    }
    catch (error) {
        debugLog('*', `Unable to parse ${filePath} (${error instanceof Error ? error.message : String(error)})`);
        return undefined;
    }
};
export class ProjectPrincipal {
    entryPaths = new Set();
    projectPaths = new Set();
    claimedEntryPaths = new Map();
    programPaths = new Set();
    skipExportsAnalysis = new Set();
    includeExportsAnalysis = new Set();
    pluginCtx = {
        filePath: '',
        sourceText: '',
        addScript: () => { },
        addImport: () => { },
        markImportExpressionHandled: () => { },
        addImportGlob: () => { },
        markExportRegistered: () => { },
    };
    pluginVisitorObjects = [];
    _visitor;
    _localRefsVisitor;
    compilers = new Map();
    scopedCompilers = new Map();
    paths = new Map();
    rootDirs = new Map();
    tsConfigFile;
    extensions = new Set(DEFAULT_EXTENSIONS);
    cache;
    toSourceFilePath;
    findWorkspacePackageTarget;
    findWorkspaceNameByFilePath;
    isReportExports;
    fileManager;
    resolveModule = () => undefined;
    resolveGlobPattern = pattern => [pattern];
    resolvedFiles = new Set();
    deletedFiles = new Set();
    onPathAdded;
    constructor(options, toSourceFilePath, findWorkspacePackageTarget, findWorkspaceNameByFilePath) {
        this.cache = new CacheConsultant('root', options);
        this.toSourceFilePath = toSourceFilePath;
        this.findWorkspacePackageTarget = findWorkspacePackageTarget;
        this.findWorkspaceNameByFilePath = findWorkspaceNameByFilePath;
        this.isReportExports = options.isReportExports;
        this.tsConfigFile = options.tsConfigFile ? toAbsolute(options.tsConfigFile, options.cwd) : undefined;
        this.pluginVisitorObjects.push(createBunShellVisitor(this.pluginCtx));
        this.fileManager = new SourceFileManager({
            compilers: this.compilers,
            isSession: options.isSession,
        });
        this.walkAndAnalyze = timerify(this.walkAndAnalyze.bind(this), 'walkAndAnalyze');
    }
    addCompilers(workspaceName, compilers) {
        for (const [ext, compiler] of compilers) {
            const workspaceCompilers = this.scopedCompilers.get(ext);
            if (workspaceCompilers) {
                workspaceCompilers.set(workspaceName, compiler);
            }
            else {
                const workspaceCompilers = new Map([[workspaceName, compiler]]);
                this.scopedCompilers.set(ext, workspaceCompilers);
                this.compilers.set(ext, (source, filePath) => {
                    const owner = this.findWorkspaceNameByFilePath(filePath);
                    return ((owner ? workspaceCompilers.get(owner) : undefined) ?? compiler)(source, filePath);
                });
                this.extensions.add(ext);
            }
        }
    }
    addPaths(paths, basePath, scope) {
        if (!paths)
            return;
        const scoped = this.paths.get(scope) ?? {};
        for (const key in paths) {
            const prefixes = paths[key].map(prefix => toAbsolute(prefix, basePath));
            scoped[key] = key in scoped ? compact([...scoped[key], ...prefixes]) : prefixes;
        }
        this.paths.set(scope, scoped);
    }
    addRootDirs(rootDirs, scope) {
        if (!rootDirs?.length)
            return;
        const scoped = this.rootDirs.get(scope) ?? [];
        this.rootDirs.set(scope, compact([...scoped, ...rootDirs]));
    }
    collectConfigurationImports(configurationFiles) {
        for (const filePath of configurationFiles.paths) {
            if (!DEFAULT_EXTENSIONS.has(extname(filePath)))
                continue;
            const source = this.fileManager.readRawFile(filePath);
            if (source === undefined)
                continue;
            try {
                for (const specifier of extractSpecifiers(_parseFile(filePath, source), source, filePath)) {
                    const resolved = this.resolveSpecifier(specifier, filePath);
                    if (resolved && !isInNodeModules(resolved))
                        configurationFiles.addImport(filePath, resolved);
                }
            }
            catch { }
        }
    }
    init() {
        const scopedPaths = this.paths.size > 0 ? Array.from(this.paths, ([scope, paths]) => ({ scope, paths })) : undefined;
        const scopedRootDirs = this.rootDirs.size > 0 ? Array.from(this.rootDirs, ([scope, rootDirs]) => ({ scope, rootDirs })) : undefined;
        this.resolveModule = createCustomModuleResolver({ scopedPaths, scopedRootDirs }, [...this.compilers.keys()], this.toSourceFilePath, this.findWorkspacePackageTarget, this.tsConfigFile);
        this.resolveGlobPattern = createGlobAliasResolver(scopedPaths);
    }
    hasAcceptedExtension(filePath) {
        return this.extensions.has(extname(filePath));
    }
    addEntryPath(filePath, options) {
        if (!isInNodeModules(filePath) && this.hasAcceptedExtension(filePath)) {
            this.claimedEntryPaths.delete(filePath);
            this.entryPaths.add(filePath);
            this.projectPaths.add(filePath);
            if (options) {
                if (options.skipExportsAnalysis) {
                    if (!this.includeExportsAnalysis.has(filePath))
                        this.skipExportsAnalysis.add(filePath);
                }
                else {
                    this.includeExportsAnalysis.add(filePath);
                    this.skipExportsAnalysis.delete(filePath);
                }
            }
            this.onPathAdded?.(filePath);
        }
    }
    addEntryPaths(filePaths, options) {
        for (const filePath of filePaths)
            this.addEntryPath(filePath, options);
    }
    addProgramPath(filePath) {
        if (!isInNodeModules(filePath) && this.hasAcceptedExtension(filePath)) {
            this.programPaths.add(filePath);
            this.onPathAdded?.(filePath);
        }
    }
    addProjectPath(filePath) {
        if (!isInNodeModules(filePath) && this.hasAcceptedExtension(filePath)) {
            this.projectPaths.add(filePath);
            this.deletedFiles.delete(filePath);
        }
    }
    claimEntryPath(filePath) {
        if (this.entryPaths.has(filePath) || isInNodeModules(filePath) || !this.hasAcceptedExtension(filePath))
            return;
        this.claimedEntryPaths.set(filePath, this.projectPaths.has(filePath));
        this.entryPaths.add(filePath);
        this.projectPaths.add(filePath);
        this.onPathAdded?.(filePath);
    }
    releaseEntryClaims() {
        for (const [filePath, isProjectPath] of this.claimedEntryPaths) {
            this.entryPaths.delete(filePath);
            if (!isProjectPath)
                this.projectPaths.delete(filePath);
        }
        this.claimedEntryPaths.clear();
    }
    removeProjectPath(filePath) {
        this.claimedEntryPaths.delete(filePath);
        this.entryPaths.delete(filePath);
        this.projectPaths.delete(filePath);
        this.skipExportsAnalysis.delete(filePath);
        this.includeExportsAnalysis.delete(filePath);
        this.invalidateFile(filePath);
        this.deletedFiles.add(filePath);
    }
    async walkAndAnalyze(analyzeFile, onSpecifier) {
        this.resolvedFiles.clear();
        const visited = new Set(this.entryPaths);
        for (const filePath of this.programPaths)
            visited.add(filePath);
        const queue = [...visited];
        const extracted = new Set();
        const enqueue = (p) => {
            if (!visited.has(p)) {
                visited.add(p);
                queue.push(p);
            }
        };
        this.onPathAdded = p => {
            if (this.projectPaths.has(p) && extracted.delete(p))
                queue.push(p);
            else
                enqueue(p);
        };
        try {
            for (let i = 0; i < queue.length; i++) {
                const filePath = queue[i];
                const isProjectPath = this.projectPaths.has(filePath);
                if (!isProjectPath)
                    extracted.add(filePath);
                const cachedFile = isProjectPath ? this.getCachedFile(filePath) : undefined;
                if (cachedFile) {
                    const internalPaths = analyzeFile(filePath, undefined, '', cachedFile);
                    if (internalPaths)
                        for (const p of internalPaths)
                            enqueue(p);
                    continue;
                }
                const loaded = this.fileManager.loadSourceText(filePath);
                const sourceText = typeof loaded === 'string' ? loaded : await loaded;
                if (!sourceText) {
                    if (isProjectPath)
                        analyzeFile(filePath, undefined, '');
                    continue;
                }
                const result = tryParseFile(filePath, sourceText);
                if (!result)
                    continue;
                this.fileManager.sourceTextCache.delete(filePath);
                if (isProjectPath) {
                    const internalPaths = analyzeFile(filePath, result, sourceText);
                    if (internalPaths)
                        for (const p of internalPaths)
                            enqueue(p);
                }
                else {
                    for (const specifier of extractSpecifiers(result, sourceText, filePath)) {
                        onSpecifier(specifier, filePath);
                        const resolved = this.resolveSpecifier(specifier, filePath);
                        if (resolved && !isInNodeModules(resolved))
                            enqueue(resolved);
                    }
                }
            }
        }
        finally {
            this.onPathAdded = undefined;
        }
        this.resolvedFiles = visited;
    }
    async getUsedResolvedFiles(onSpecifier) {
        this.resolvedFiles.clear();
        const visited = new Set([...this.entryPaths, ...this.programPaths]);
        this.onPathAdded = p => visited.add(p);
        try {
            for (const filePath of visited) {
                const loaded = this.fileManager.loadSourceText(filePath);
                const sourceText = typeof loaded === 'string' ? loaded : await loaded;
                if (!sourceText)
                    continue;
                const result = tryParseFile(filePath, sourceText);
                if (!result)
                    continue;
                const isProjectPath = this.projectPaths.has(filePath);
                for (const specifier of extractSpecifiers(result, sourceText, filePath)) {
                    const resolved = this.resolveSpecifier(specifier, filePath);
                    onSpecifier(specifier, filePath, isProjectPath && getSubpathImport(specifier) ? resolved : undefined);
                    if (resolved && !isInNodeModules(resolved))
                        visited.add(resolved);
                }
            }
        }
        finally {
            this.onPathAdded = undefined;
        }
        this.resolvedFiles = visited;
        const usedFiles = new Set();
        for (const filePath of this.projectPaths)
            if (visited.has(filePath))
                usedFiles.add(filePath);
        return usedFiles;
    }
    resolveSpecifier(specifier, containingFile) {
        return this.resolveModule(specifier, containingFile)?.resolvedFileName;
    }
    getUnreferencedFiles() {
        return Array.from(this.projectPaths).filter(filePath => !this.resolvedFiles.has(filePath));
    }
    getCachedFile(filePath) {
        const cachedFile = this.cache.getCachedFile(filePath);
        const skipExports = this.skipExportsAnalysis.has(filePath) || !this.isReportExports;
        return cachedFile?.skipExports === skipExports ? copyFileNode(cachedFile) : undefined;
    }
    analyzeSourceFile(filePath, sourceText, options, ignoreExportsUsedInFile, parseResult, cachedFile) {
        if (cachedFile)
            return cachedFile;
        const cached = this.getCachedFile(filePath);
        if (cached)
            return cached;
        const skipExports = this.skipExportsAnalysis.has(filePath);
        if (options.isFixExports || options.isFixTypes) {
            const ext = extname(filePath);
            if (!DEFAULT_EXTENSIONS.has(ext) && this.compilers.has(ext)) {
                options = { ...options, isFixExports: false, isFixTypes: false };
            }
        }
        const visitor = ignoreExportsUsedInFile
            ? (this._localRefsVisitor ??= buildVisitor(this.pluginVisitorObjects, true))
            : (this._visitor ??= buildVisitor(this.pluginVisitorObjects, false));
        const file = _getImportsAndExports(filePath, sourceText, this.resolveModule, options, ignoreExportsUsedInFile, skipExports, visitor, this.pluginVisitorObjects.length > 0 ? this.pluginCtx : undefined, parseResult);
        if (this.projectPaths.has(filePath))
            this.cache.setFileData(filePath, copyFileNode(file));
        return file;
    }
    invalidateFile(filePath) {
        this.fileManager.invalidate(filePath);
        this.cache.removeEntry(filePath);
    }
    reconcileCache() {
        this.cache.reconcile();
    }
}
