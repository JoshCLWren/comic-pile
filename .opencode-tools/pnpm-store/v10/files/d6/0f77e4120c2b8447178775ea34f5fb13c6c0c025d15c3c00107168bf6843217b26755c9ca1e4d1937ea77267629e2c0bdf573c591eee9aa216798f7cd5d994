import { _getInputsFromScripts } from '../binaries/index.js';
import { isDefaultPattern } from '../ConfigurationChief.js';
import { getIncludedCompilers, normalizeCompilerExtension } from '../compilers/index.js';
import { DEFAULT_EXTENSIONS, FOREIGN_FILE_EXTENSIONS, IS_DTS, ROOT_WORKSPACE_NAME } from '../constants.js';
import { partition } from '../util/array.js';
import { createInputHandler } from '../util/create-input-handler.js';
import { ConfigurationFiles } from '../session/configuration.js';
import { debugLog, debugLogArray } from '../util/debug.js';
import { existsSync } from 'node:fs';
import picomatch from 'picomatch';
import { isDynamicPattern } from 'tinyglobby';
import { tryRealpath } from '../util/fs.js';
import { createManifest } from '../util/package-json.js';
import { _glob, _syncGlob, prependDirToPattern as prependDir, rebasePattern, removeProductionSuffix, } from '../util/glob.js';
import { isAlias, isCatalog, isConfig, isEntry, isIgnore, isProductionEntry, isProject, toEntryPath, toDependency, toEntry, } from '../util/input.js';
import { isAmbientDeclarationFile } from '../typescript/ast-nodes.js';
import { resolveImportGlobs } from '../typescript/glob-imports.js';
import { createPublishedTypeDependencyAnalyzer } from '../typescript/get-published-type-dependencies.js';
import { loadTSConfig } from '../util/load-tsconfig.js';
import { createFileNode, updateImportMap } from '../util/module-graph.js';
import { getPackageNameFromModuleSpecifier, isStartsLikePackageName, sanitizeSpecifier } from '../util/modules.js';
import { perfObserver, timerify } from '../util/Performance.js';
import { getEntrySpecifiersFromManifest, getManifestImportDependencies } from '../util/package-json.js';
import { expandIgnorePatterns } from '../util/parse-and-convert-gitignores.js';
import { dirname, extname, isAbsolute, isInNodeModules, isInternal, join, relative } from '../util/path.js';
import { extensionAlias } from '../util/resolve.js';
import { augmentWorkspace, getToSourcePathsHandler, toSourceMappedSpecifiers } from '../util/to-source-path.js';
import { WorkspaceWorker } from '../WorkspaceWorker.js';
export const build = timerify(async function build({ chief, collector, counselor, deputy, principal, isGitIgnored, scriptParserContext, streamer, subpathReferences, workspaces, options, }) {
    const configFilesMap = new Map();
    const configurationFiles = options.isSession ? new ConfigurationFiles(options) : undefined;
    const enabledPluginsStore = new Map();
    const registeredVisitorPlugins = new Set();
    const toSourceFilePaths = getToSourcePathsHandler(chief);
    const addIssue = (issue) => collector.addIssue(issue) && options.isSession && collector.retainIssue(issue);
    const externalRefsFromInputs = options.isSession ? new Map() : undefined;
    const resolveInput = createInputHandler(deputy, chief, isGitIgnored, addIssue, externalRefsFromInputs, options);
    const handleInput = (input, workspace, owner = workspace.manifestPath) => {
        subpathReferences.addInput(input, owner);
        return resolveInput(input, workspace);
    };
    const getPublishedTypeDependencies = options.isReportDependencies
        ? createPublishedTypeDependencyAnalyzer()
        : undefined;
    const { rootManifest, getManifest } = scriptParserContext;
    for (const workspace of workspaces) {
        const { name, dir, manifestPath, manifestStr } = workspace;
        const manifest = chief.getManifestForWorkspace(name);
        if (!manifest)
            continue;
        deputy.addWorkspace({
            name,
            dir,
            manifestPath,
            manifestStr,
            manifest,
            ...chief.getIgnores(name),
        });
    }
    if (!deputy.getWorkspaceManifest(ROOT_WORKSPACE_NAME))
        deputy.setRootIgnores(chief.getIgnores(ROOT_WORKSPACE_NAME));
    deputy.setWorkspacePkgNames(chief.availableWorkspacePkgNames);
    collector.addIgnorePatterns(chief.config.ignore.map(id => ({ pattern: id, id })));
    collector.addIgnoreFilesPatterns(chief.config.ignoreFiles.map(id => ({ pattern: id, id })));
    if (options.configFilePath) {
        principal.addEntryPath(options.configFilePath, { skipExportsAnalysis: true });
    }
    const preprocessorInputs = new Map();
    for (const specifier of options.preprocessorInputs) {
        const containingFilePath = options.configFilePath ?? join(options.cwd, 'package.json');
        const isLocal = isInternal(specifier);
        const input = isLocal
            ? toEntryPath(specifier, { containingFilePath })
            : toDependency(specifier, { containingFilePath, optional: true });
        const owner = isLocal ? chief.findWorkspaceByFilePath(specifier)?.name : undefined;
        const name = owner ?? ROOT_WORKSPACE_NAME;
        const inputs = preprocessorInputs.get(name);
        if (inputs)
            inputs.push(input);
        else
            preprocessorInputs.set(name, [input]);
    }
    for (const workspace of workspaces) {
        const { name, dir, ancestors, config: baseConfig, manifestPath: filePath } = workspace;
        streamer.cast('Analyzing workspace', name);
        const manifest = chief.getManifestForWorkspace(name);
        if (!manifest)
            continue;
        const dependencies = deputy.getDependencies(name);
        const tsConfigFilePath = join(dir, options.tsConfigFile ?? 'tsconfig.json');
        configurationFiles?.paths.add(filePath);
        configurationFiles?.paths.add(tsConfigFilePath);
        const { isFile, compilerOptions, fileNames, include, exclude, sourceMapPairs, paths: tsConfigPaths, } = await loadTSConfig(tsConfigFilePath, options.isUseTscFiles);
        const [definitionPaths, tscSourcePaths] = partition(fileNames, filePath => IS_DTS.test(filePath));
        const worker = new WorkspaceWorker({
            name,
            dir,
            configKey: workspace.configKey,
            config: baseConfig,
            manifest,
            dependencies,
            allDependencies: deputy.getAllDependencies(name),
            rootManifest,
            handleInput: (input) => handleInput(input, workspace),
            handleConfigLoadError: () => collector.addConfigLoadError(),
            findWorkspaceByFilePath: chief.findWorkspaceByFilePath.bind(chief),
            getManifest,
            negatedWorkspacePatterns: chief.getNegatedWorkspacePatterns(name),
            ignoredWorkspacePatterns: chief.getIgnoredWorkspacesFor(name),
            enabledPluginsInAncestors: ancestors.flatMap(ancestor => enabledPluginsStore.get(ancestor) ?? []),
            readRawFile: (filePath) => principal.fileManager.readRawFile(filePath) ?? '',
            configFilesMap,
            configurationFiles,
            options,
        });
        await worker.init();
        const compilers = getIncludedCompilers(chief.config.compilers, dependencies, dep => deputy.addReferencedDependency(name, dep));
        const registerCompiler = ({ extension, compiler }) => {
            const ext = normalizeCompilerExtension(extension);
            if (compilers.has(ext))
                return;
            compilers.set(ext, compiler);
        };
        await worker.registerCompilers(registerCompiler);
        principal.addCompilers(name, compilers);
        const extensions = [...compilers.keys()];
        const extensionGlobStr = `.{${[...DEFAULT_EXTENSIONS, ...extensions].map(ext => ext.slice(1)).join(',')}}`;
        const config = chief.getConfigForWorkspace(name, extensions);
        worker.config = config;
        const pluginSourceMaps = await worker.resolveSourceMaps();
        augmentWorkspace(workspace, dir, isFile ? compilerOptions : undefined, [...pluginSourceMaps, ...sourceMapPairs]);
        const inputs = new Set(preprocessorInputs.get(name));
        if (definitionPaths.length > 0) {
            debugLogArray(name, 'Definition paths', definitionPaths);
            for (const id of definitionPaths)
                inputs.add(toEntry(tryRealpath(id), { production: true, containingFilePath: tsConfigFilePath }));
        }
        const sharedGlobOptions = { cwd: options.cwd, dir, gitignore: options.gitignore };
        const fn = (id) => ({
            pattern: prependDir(name, id),
            id,
            workspaceName: name,
            configKey: workspace.configKey,
        });
        collector.addIgnorePatterns(config.ignore.map(fn));
        collector.addIgnoreFilesPatterns(config.ignoreFiles.map(fn));
        const entrySpecifiersFromManifest = getEntrySpecifiersFromManifest(manifest, config.isIncludeSubpathExports);
        const label = 'entry paths from package.json';
        for (const filePath of await toSourceFilePaths(entrySpecifiersFromManifest, dir, extensionGlobStr, label)) {
            if (!isGitIgnored(filePath))
                inputs.add(toEntry(filePath, { production: true }));
        }
        if (getPublishedTypeDependencies && !manifest.private && !manifest.publishConfig?.directory) {
            for (const dependency of getPublishedTypeDependencies(workspace, manifest)) {
                const isHandled = deputy.maybeAddReferencedExternalDependency(workspace, dependency.packageName, {
                    specifier: dependency.specifier,
                    isTypeOnly: true,
                    isResolved: dependency.isResolved,
                    isPublishedType: true,
                });
                if (!isHandled) {
                    addIssue({
                        type: 'unlisted',
                        filePath: dependency.containingFilePath,
                        workspace: name,
                        symbol: dependency.packageName,
                        specifier: dependency.specifier,
                        pos: dependency.pos,
                        line: dependency.line,
                        col: dependency.col,
                        fixes: [],
                    });
                }
            }
        }
        for (const identifier of entrySpecifiersFromManifest) {
            if (identifier.startsWith('!') || isGitIgnored(join(dir, identifier)))
                continue;
            if (!identifier.startsWith('.') && !identifier.startsWith('/')) {
                const packageName = getPackageNameFromModuleSpecifier(identifier);
                if (packageName && dependencies.has(packageName))
                    continue;
            }
            const abs = prependDir(dir, identifier);
            const mapped = toSourceMappedSpecifiers(workspace, abs, extensionGlobStr);
            const hasWildcard = identifier.includes('*');
            const exists = hasWildcard
                ? _syncGlob({ patterns: [identifier, ...mapped], cwd: dir }).length > 0
                : existsSync(abs) || mapped.some(pattern => _syncGlob({ patterns: [pattern], cwd: dir }).length > 0);
            if (!exists) {
                collector.addConfigurationHint({ type: 'package-entry', filePath, identifier, workspaceName: name });
            }
        }
        for (const dep of getManifestImportDependencies(manifest))
            deputy.addReferencedDependency(name, dep);
        principal.addPaths(config.paths, dir, dir);
        if (tsConfigPaths)
            principal.addPaths(tsConfigPaths, dir, dir);
        principal.addRootDirs(compilerOptions.rootDirs, dir);
        const inputsFromPlugins = await worker.runPlugins();
        for (const id of inputsFromPlugins)
            inputs.add(Object.assign(id, { skipExportsAnalysis: !id.allowIncludeExports }));
        enabledPluginsStore.set(name, worker.enabledPlugins);
        worker.registerVisitors({
            ctx: principal.pluginCtx,
            registerVisitor: visitors => principal.pluginVisitorObjects.push(visitors),
            registeredPlugins: registeredVisitorPlugins,
        });
        const DEFAULT_GROUP = 'default';
        const createPatternMap = () => new Map([[DEFAULT_GROUP, new Set()]]);
        const groups = new Map([[DEFAULT_GROUP, undefined]]);
        const entryPatterns = createPatternMap();
        const entryPatternsSkipExports = createPatternMap();
        const productionPatterns = createPatternMap();
        const productionPatternsSkipExports = createPatternMap();
        const projectFilePatterns = new Set();
        const addPattern = (map, group, pattern) => {
            let patterns = map.get(group);
            if (!patterns)
                map.set(group, (patterns = new Set()));
            patterns.add(pattern);
        };
        const toWorkspaceRelative = (path) => (isAbsolute(path) ? relative(dir, path) : path);
        const addEntryPattern = (map, input) => {
            const base = input.dir;
            if (base && base !== dir) {
                const group = `${input.group ?? DEFAULT_GROUP}:${base}`;
                groups.set(group, base);
                addPattern(map, group, rebasePattern(input.specifier, base, dir));
            }
            else {
                addPattern(map, input.group ?? DEFAULT_GROUP, toWorkspaceRelative(input.specifier));
            }
        };
        for (const input of inputs) {
            if (input.group)
                groups.set(input.group, undefined);
            const specifier = input.specifier;
            if (isCatalog(input)) {
                counselor.addReference({ catalogName: input.catalogName, packageName: specifier });
            }
            else if (isEntry(input)) {
                addEntryPattern(input.skipExportsAnalysis ? entryPatternsSkipExports : entryPatterns, input);
            }
            else if (isProductionEntry(input)) {
                addEntryPattern(input.skipExportsAnalysis ? productionPatternsSkipExports : productionPatterns, input);
            }
            else if (isProject(input)) {
                projectFilePatterns.add(toWorkspaceRelative(specifier));
            }
            else if (isAlias(input)) {
                principal.addPaths({ [input.specifier]: input.prefixes }, input.dir ?? dir, dir);
            }
            else if (isIgnore(input)) {
                if (input.issueType === 'dependencies' || input.issueType === 'unlisted') {
                    deputy.addIgnoredDependencies(name, input.specifier);
                }
                else if (input.issueType === 'binaries') {
                    deputy.addIgnoredBinaries(name, input.specifier);
                }
                else if (input.issueType === 'unresolved') {
                    deputy.addIgnoredUnresolved(name, input.specifier);
                }
            }
            else if (!isConfig(input)) {
                const ws = (input.containingFilePath && chief.findWorkspaceByFilePath(input.containingFilePath)) || workspace;
                const resolvedFilePath = handleInput(input, ws);
                if (resolvedFilePath) {
                    if (options.isProduction && !input.production) {
                        if (!input.optional)
                            collector.addReferencedFile(resolvedFilePath);
                    }
                    else {
                        principal.addEntryPath(resolvedFilePath, { skipExportsAnalysis: input.skipExportsAnalysis ?? true });
                    }
                }
            }
        }
        const developmentMatchers = [];
        if (options.isProduction) {
            const toPattern = (pattern) => {
                const id = removeProductionSuffix(pattern);
                return isAbsolute(id) ? relative(options.cwd, id) : join(name, id);
            };
            for (const map of [entryPatterns, entryPatternsSkipExports]) {
                for (const patterns of map.values()) {
                    const [excluded, included] = partition(patterns, pattern => pattern.startsWith('!'));
                    if (included.length === 0)
                        continue;
                    const ignore = expandIgnorePatterns(excluded.map(pattern => removeProductionSuffix(pattern.slice(1))));
                    developmentMatchers.push(picomatch(included.map(toPattern), { ignore: ignore.map(toPattern), dot: true }));
                }
            }
        }
        const productionPaths = (paths) => developmentMatchers.length
            ? paths.filter(path => {
                const relativePath = relative(options.cwd, path);
                return !developmentMatchers.some(match => match(relativePath));
            })
            : paths;
        const userEntryPatterns = options.isProduction
            ? worker.getProductionEntryFilePatterns()
            : worker.getEntryFilePatterns();
        const userEntryPaths = await _glob({
            ...sharedGlobOptions,
            patterns: userEntryPatterns,
            gitignore: false,
            label: 'entry paths',
        });
        for (const [group, base] of groups) {
            {
                const patterns = worker.getPluginEntryFilePatterns([...((!options.isProduction && entryPatterns.get(group)) || []), ...(productionPatterns.get(group) ?? [])], base);
                const label = `entry paths from plugins${group !== DEFAULT_GROUP ? ` - ${group}` : ''}`;
                const pluginWorkspaceEntryPaths = await _glob({ ...sharedGlobOptions, patterns, label });
                principal.addEntryPaths(productionPaths(pluginWorkspaceEntryPaths));
            }
            {
                const patterns = worker.getPluginEntryFilePatterns([
                    ...((!options.isProduction && entryPatternsSkipExports.get(group)) || []),
                    ...(productionPatternsSkipExports.get(group) ?? []),
                ], base);
                const label = `entry paths from plugins (ignore exports)${group !== DEFAULT_GROUP ? ` - ${group}` : ''}`;
                const pluginWorkspaceEntryPaths = await _glob({ ...sharedGlobOptions, patterns, label });
                principal.addEntryPaths(pluginWorkspaceEntryPaths, { skipExportsAnalysis: true });
            }
        }
        if (!options.isProduction) {
            const includedPaths = config.isIncludeEntryExports
                ? new Set([...principal.entryPaths].filter(filePath => !principal.skipExportsAnalysis.has(filePath)))
                : principal.entryPaths;
            const hints = worker.getConfigurationHints('entry', userEntryPatterns, userEntryPaths, includedPaths);
            for (const hint of hints)
                collector.addConfigurationHint(hint);
        }
        const hasExplicitEntries = config.entry.some(pattern => !isDefaultPattern('entry', pattern));
        principal.addEntryPaths(productionPaths(userEntryPaths), hasExplicitEntries ? { skipExportsAnalysis: false } : undefined);
        if (options.isUseTscFiles && isFile) {
            const isIgnoredWorkspace = chief.createIgnoredWorkspaceMatcher(name, dir);
            debugLogArray(name, 'Using tsconfig files as project files', tscSourcePaths);
            for (const tscPath of tscSourcePaths) {
                const filePath = tryRealpath(tscPath);
                if (!isGitIgnored(filePath) && !isIgnoredWorkspace(filePath)) {
                    principal.addProgramPath(filePath);
                    principal.addProjectPath(filePath);
                }
            }
            if (extensions.length > 0) {
                const extPart = extensions.length === 1 ? extensions[0] : `.{${extensions.map(ext => ext.slice(1)).join(',')}}`;
                const tsConfigDir = relative(dir, dirname(tsConfigFilePath));
                const bases = include ? new Set(include.map(p => join(tsConfigDir, picomatch.scan(p).base))) : new Set(['']);
                const patterns = [
                    ...Array.from(bases, base => join(base, `**/*${extPart}`)),
                    ...(exclude?.map(p => `!${join(tsConfigDir, p)}`) ?? []),
                ];
                const compilerPaths = await _glob({ ...sharedGlobOptions, patterns, label: 'compiler extension paths' });
                for (const compilerPath of compilerPaths) {
                    if (!isIgnoredWorkspace(compilerPath))
                        principal.addProjectPath(compilerPath);
                }
            }
        }
        else {
            const patterns = options.isProduction
                ? worker.getProductionProjectFilePatterns()
                : worker.getProjectFilePatterns([
                    ...(productionPatternsSkipExports.get(DEFAULT_GROUP) ?? []),
                    ...projectFilePatterns,
                    ...worker.getPluginProjectFilePatterns(),
                ]);
            const projectPaths = await _glob({ ...sharedGlobOptions, patterns, label: 'project paths' });
            if (!options.isProduction) {
                const hints = worker.getConfigurationHints('project', config.project, projectPaths, principal.projectPaths, new Set(extensions));
                for (const hint of hints)
                    collector.addConfigurationHint(hint);
            }
            for (const projectPath of productionPaths(projectPaths))
                principal.addProjectPath(projectPath);
        }
        worker.onDispose();
        perfObserver.addMemoryMark(name);
    }
    debugLog('*', `Created 1 principal for ${workspaces.length} workspaces`);
    const graph = new Map();
    const analyzedFiles = new Set();
    const unreferencedFiles = new Set();
    const analyzeOpts = {
        isFixExports: options.isFixUnusedExports,
        isFixTypes: options.isFixUnusedTypes,
        isReportExports: options.isReportExports,
        skipTypeOnly: options.isStrict,
        tags: options.tags,
    };
    const analyzeSourceFile = (filePath, sourceText, parseResult, cachedFile) => {
        if (!options.isSession && analyzedFiles.has(filePath))
            return;
        analyzedFiles.add(filePath);
        subpathReferences.release(filePath);
        const workspace = chief.findWorkspaceByFilePath(filePath);
        if (workspace) {
            const file = principal.analyzeSourceFile(filePath, sourceText, analyzeOpts, workspace.config.ignoreExportsUsedInFile, parseResult, cachedFile);
            const unresolvedImports = new Set();
            for (const unresolvedImport of file.imports.unresolved) {
                const { specifier } = unresolvedImport;
                if (specifier.startsWith('http'))
                    continue;
                const sanitizedSpecifier = sanitizeSpecifier(specifier);
                if (isStartsLikePackageName(sanitizedSpecifier)) {
                    file.imports.external.add({ ...unresolvedImport, specifier: sanitizedSpecifier });
                    subpathReferences.add(sanitizedSpecifier, filePath);
                }
                else {
                    const candidate = join(dirname(filePath), sanitizedSpecifier);
                    const ext = extname(sanitizedSpecifier);
                    const aliases = extensionAlias[ext];
                    let isIgnored = isGitIgnored(candidate);
                    if (!isIgnored && aliases) {
                        const basePath = candidate.slice(0, -ext.length);
                        for (const alias of aliases) {
                            if (alias !== ext && isGitIgnored(basePath + alias)) {
                                isIgnored = true;
                                break;
                            }
                        }
                    }
                    if (!isIgnored && (!ext || (ext !== '.json' && !FOREIGN_FILE_EXTENSIONS.has(ext)))) {
                        unresolvedImports.add(unresolvedImport);
                    }
                }
            }
            for (const filePath of file.imports.programFiles) {
                const isIgnored = isGitIgnored(filePath);
                if (!isIgnored)
                    principal.addProgramPath(filePath);
            }
            for (const filePath of file.imports.entryFiles) {
                const isIgnored = isGitIgnored(filePath);
                if (!isIgnored)
                    principal.addEntryPath(filePath, { skipExportsAnalysis: true });
            }
            if (file.imports.subpathImports) {
                for (const [specifier, importedFilePath] of file.imports.subpathImports)
                    subpathReferences.add(specifier, filePath, importedFilePath);
            }
            const wsDependencies = deputy.getDependencies(workspace.name);
            for (const _import of file.imports.imports) {
                if (!_import.filePath)
                    continue;
                const packageName = getPackageNameFromModuleSpecifier(_import.specifier);
                if (!packageName)
                    continue;
                const isWorkspace = chief.isWorkspacePackageName(packageName);
                if (isWorkspace || wsDependencies.has(packageName)) {
                    file.imports.external.add({ ..._import, specifier: packageName });
                    if (isWorkspace)
                        subpathReferences.add(_import.specifier, filePath);
                }
            }
            const manifest = chief.getManifestForWorkspace(workspace.name);
            if (manifest && file.scripts && file.scripts.size > 0) {
                const dependencies = deputy.getDependencies(workspace.name);
                const dir = dirname(filePath);
                const opts = {
                    cwd: dir,
                    manifestDir: workspace.dir,
                    rootCwd: options.cwd,
                    containingFilePath: filePath,
                    dependencies,
                    manifest: createManifest(manifest),
                    rootManifest,
                    getManifest,
                };
                const inputs = _getInputsFromScripts(file.scripts, opts);
                for (const input of inputs) {
                    if (isCatalog(input)) {
                        counselor.addReference({ catalogName: input.catalogName, packageName: input.specifier });
                        continue;
                    }
                    input.containingFilePath ??= filePath;
                    input.dir ??= dir;
                    if (options.isProduction)
                        input.production = true;
                    if (input.type === 'entry' && isDynamicPattern(input.specifier)) {
                        for (const entryPath of _syncGlob({ patterns: input.specifier, cwd: input.dir })) {
                            if (!isGitIgnored(entryPath))
                                principal.addEntryPath(entryPath, { skipExportsAnalysis: true });
                        }
                        continue;
                    }
                    const specifierFilePath = handleInput(input, workspace, filePath);
                    if (specifierFilePath)
                        principal.addEntryPath(specifierFilePath, { skipExportsAnalysis: true });
                }
            }
            if (file.importGlobs.length > 0) {
                const [analyzedImportGlobs, entryImportGlobs] = partition(file.importGlobs, glob => glob.analyzeExports);
                const analyzed = resolveImportGlobs(analyzedImportGlobs, filePath, principal.resolveGlobPattern, workspace.dir);
                for (const importedFilePath of analyzed) {
                    if (!isGitIgnored(importedFilePath))
                        principal.addProgramPath(importedFilePath);
                }
                const entries = resolveImportGlobs(entryImportGlobs, filePath, principal.resolveGlobPattern, workspace.dir);
                for (const importedFilePath of entries) {
                    if (!isGitIgnored(importedFilePath))
                        principal.addEntryPath(importedFilePath, { skipExportsAnalysis: true });
                }
            }
            file.imports.unresolved = unresolvedImports;
            const pluginRefs = externalRefsFromInputs?.get(filePath);
            if (pluginRefs)
                for (const ref of pluginRefs)
                    file.imports.externalRefs.add(ref);
            const node = graph.get(filePath);
            if (node) {
                node.skipExports = file.skipExports;
                node.imports = file.imports;
                node.exports = file.exports;
                node.duplicates = file.duplicates;
                node.scripts = file.scripts;
                node.importGlobs = file.importGlobs;
                updateImportMap(node, file.imports.internal, graph);
                node.internalImportCache = file.imports.internal;
            }
            else {
                updateImportMap(file, file.imports.internal, graph);
                file.internalImportCache = file.imports.internal;
                graph.set(filePath, file);
            }
        }
    };
    principal.init();
    subpathReferences.reset();
    streamer.cast('Analyzing source files');
    await principal.walkAndAnalyze((filePath, parseResult, sourceText, cachedFile) => {
        analyzeSourceFile(filePath, sourceText, parseResult, cachedFile);
        const node = graph.get(filePath);
        if (!node)
            return;
        const paths = [];
        for (const importPath of node.imports.internal.keys()) {
            if (!isInNodeModules(importPath))
                paths.push(importPath);
        }
        return paths;
    }, (specifier, filePath) => subpathReferences.add(specifier, filePath));
    for (const filePath of principal.getUnreferencedFiles()) {
        if (IS_DTS.test(filePath)) {
            const loaded = principal.fileManager.loadSourceText(filePath);
            const sourceText = typeof loaded === 'string' ? loaded : await loaded;
            principal.fileManager.sourceTextCache.delete(filePath);
            if (isAmbientDeclarationFile(filePath, sourceText))
                continue;
        }
        unreferencedFiles.add(filePath);
    }
    principal.reconcileCache();
    perfObserver.addMemoryMark('build');
    if (externalRefsFromInputs) {
        for (const [filePath, refs] of externalRefsFromInputs) {
            if (!graph.has(filePath))
                graph.set(filePath, createFileNode());
            for (const ref of refs)
                graph.get(filePath).imports.externalRefs.add(ref);
        }
    }
    return {
        graph,
        configurationFiles,
        entryPaths: principal.entryPaths,
        analyzedFiles,
        unreferencedFiles,
        analyzeSourceFile: async (filePath) => {
            const loaded = principal.fileManager.loadSourceText(filePath);
            const sourceText = typeof loaded === 'string' ? loaded : await loaded;
            analyzeSourceFile(filePath, sourceText);
        },
        enabledPluginsStore,
    };
});
