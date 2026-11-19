import picomatch from 'picomatch';
import { isDynamicPattern } from 'tinyglobby';
import { _getInputsFromScripts } from './binaries/index.js';
import { getScriptCommands } from './binaries/plugins.js';
import { CacheConsultant } from './CacheConsultant.js';
import { isDefaultPattern } from './ConfigurationChief.js';
import { DEFAULT_EXTENSIONS, ROOT_WORKSPACE_NAME } from './constants.js';
import { getFilteredScripts } from './manifest/helpers.js';
import { PluginEntries, Plugins } from './plugins.js';
import { createManifest } from './util/package-json.js';
import { isExternalReExportsOnly } from './typescript/ast-helpers.js';
import { _parseFile } from './typescript/ast-nodes.js';
import { compact } from './util/array.js';
import { debugLog, debugLogArray, debugLogObject } from './util/debug.js';
import { _glob, hasNoProductionSuffix, hasProductionSuffix, negate } from './util/glob.js';
import { expandIgnorePatterns } from './util/parse-and-convert-gitignores.js';
import { isConfig, isEntry, toDebugString, toEntry } from './util/input.js';
import { filterTransitiveDependencies } from './util/filter-transitive-dependencies.js';
import { timerify } from './util/Performance.js';
import { basename, dirname, extname, join, relative, toRelative } from './util/path.js';
import { extractPatternExtensions } from './util/pattern-extensions.js';
import { formatCauseMessage } from './util/errors.js';
import { logError } from './util/log.js';
import { loadConfigForPlugin } from './util/plugin.js';
import { hasUnhandledRejection, trackConfigLoad } from './util/unhandled-rejection.js';
const nullConfig = { config: null, entry: null, project: null };
export class WorkspaceWorker {
    name;
    dir;
    configKey;
    config;
    manifest;
    rootManifest;
    dependencies;
    allDependencies;
    handleInput;
    handleConfigLoadError;
    findWorkspaceByFilePath;
    getManifest;
    readRawFile;
    negatedWorkspacePatterns = [];
    ignoredWorkspacePatterns = [];
    options;
    enabledPluginsMap = {};
    enabledPlugins = [];
    enabledPluginsInAncestors;
    cache;
    configFilesMap;
    configurationFiles;
    constructor({ name, dir, configKey, config, manifest, dependencies, allDependencies, rootManifest, negatedWorkspacePatterns, ignoredWorkspacePatterns, enabledPluginsInAncestors, handleInput, handleConfigLoadError, findWorkspaceByFilePath, getManifest, readRawFile, configFilesMap, configurationFiles, options, }) {
        this.name = name;
        this.dir = dir;
        this.configKey = configKey;
        this.config = config;
        this.manifest = createManifest(manifest);
        this.rootManifest = rootManifest;
        this.dependencies = dependencies;
        this.allDependencies = allDependencies;
        this.negatedWorkspacePatterns = negatedWorkspacePatterns;
        this.ignoredWorkspacePatterns = ignoredWorkspacePatterns;
        this.enabledPluginsInAncestors = enabledPluginsInAncestors;
        this.configFilesMap = configFilesMap;
        this.configurationFiles = configurationFiles;
        this.handleInput = handleInput;
        this.handleConfigLoadError = handleConfigLoadError;
        this.findWorkspaceByFilePath = findWorkspaceByFilePath;
        this.getManifest = getManifest;
        this.readRawFile = readRawFile;
        this.options = options;
        this.cache = new CacheConsultant(`plugins-${name}`, options);
        this.getConfigurationHints = timerify(this.getConfigurationHints.bind(this), 'getConfigurationHints');
    }
    async init() {
        this.enabledPlugins = await this.determineEnabledPlugins();
    }
    async determineEnabledPlugins() {
        const manifest = this.manifest;
        const enabledPlugins = [];
        for (const [pluginName, plugin] of PluginEntries) {
            if (this.config[pluginName] === false)
                continue;
            if (this.options.cwd !== this.dir && plugin.isRootOnly)
                continue;
            if (this.config[pluginName]) {
                this.enabledPluginsMap[pluginName] = true;
                enabledPlugins.push(pluginName);
                continue;
            }
            const isEnabledInAncestor = this.enabledPluginsInAncestors.includes(pluginName);
            if (isEnabledInAncestor ||
                (typeof plugin.isEnabled === 'function' &&
                    (await plugin.isEnabled({
                        cwd: this.dir,
                        manifest,
                        dependencies: this.dependencies,
                        config: this.config,
                        getScriptCommands,
                    })))) {
                this.enabledPluginsMap[pluginName] = true;
                enabledPlugins.push(pluginName);
            }
        }
        return enabledPlugins;
    }
    getConfigForPlugin(pluginName) {
        const config = this.config[pluginName];
        return typeof config === 'undefined' || typeof config === 'boolean' ? nullConfig : config;
    }
    getEntryFilePatterns() {
        const { entry } = this.config;
        if (entry.length === 0)
            return [];
        const excludeProductionNegations = entry.filter(pattern => !(pattern.startsWith('!') && pattern.endsWith('!')));
        return [excludeProductionNegations, this.negatedWorkspacePatterns].flat();
    }
    getProjectFilePatterns(projectFilePatterns) {
        const { project } = this.config;
        if (project.length === 0)
            return [];
        const excludeProductionNegations = project.filter(pattern => !(pattern.startsWith('!') && pattern.endsWith('!')));
        return [excludeProductionNegations, projectFilePatterns, this.negatedWorkspacePatterns].flat();
    }
    getPluginProjectFilePatterns(patterns = []) {
        for (const [pluginName, plugin] of PluginEntries) {
            const pluginConfig = this.getConfigForPlugin(pluginName);
            if (this.enabledPluginsMap[pluginName]) {
                const { entry, project } = pluginConfig;
                patterns.push(...(project ?? entry ?? plugin.project ?? []));
            }
        }
        return [patterns, this.negatedWorkspacePatterns].flat();
    }
    getPluginConfig(plugin) {
        return typeof plugin.config === 'function' ? plugin.config({ cwd: this.dir }) : plugin.config;
    }
    getPluginConfigPatterns() {
        const patterns = [];
        for (const [pluginName, plugin] of PluginEntries) {
            const pluginConfig = this.getConfigForPlugin(pluginName);
            if (this.enabledPluginsMap[pluginName] && pluginConfig) {
                patterns.push(...(pluginConfig.config ?? this.getPluginConfig(plugin) ?? []));
            }
        }
        return patterns;
    }
    getPluginEntryFilePatterns(patterns, base) {
        const negateWorkspaces = patterns.some(pattern => pattern.startsWith('**/')) ? this.negatedWorkspacePatterns : [];
        const prefix = `${this.name}/`;
        const toWorkspaceRelative = (name) => (name.startsWith(prefix) ? name.slice(prefix.length) : name);
        const ignoredWorkspaces = base
            ? expandIgnorePatterns(this.ignoredWorkspacePatterns.map(toWorkspaceRelative))
            : this.ignoredWorkspacePatterns;
        return [patterns, negateWorkspaces, ignoredWorkspaces.map(negate)].flat();
    }
    getProductionEntryFilePatterns() {
        const entry = this.config.entry.filter(hasProductionSuffix);
        if (entry.length === 0)
            return [];
        const negatedEntryFiles = this.config.entry.filter(hasNoProductionSuffix).map(negate);
        return [entry, negatedEntryFiles, this.negatedWorkspacePatterns].flat();
    }
    getProductionProjectFilePatterns() {
        const project = this.config.project;
        if (project.length === 0)
            return this.getProductionEntryFilePatterns();
        const _project = this.config.project.map(pattern => {
            if (!(pattern.endsWith('!') || pattern.startsWith('!')))
                return negate(pattern);
            return pattern;
        });
        const negatedEntryFiles = this.config.entry.filter(hasNoProductionSuffix).map(negate);
        const negatedPluginConfigPatterns = this.getPluginConfigPatterns().map(negate);
        const negatedPluginProjectFilePatterns = this.getPluginProjectFilePatterns().map(negate);
        return [
            _project,
            negatedEntryFiles,
            negatedPluginConfigPatterns,
            negatedPluginProjectFilePatterns,
            this.negatedWorkspacePatterns,
        ].flat();
    }
    getConfigurationFilePatterns(pluginName) {
        const plugin = Plugins[pluginName];
        const pluginConfig = this.getConfigForPlugin(pluginName);
        return pluginConfig.config ?? this.getPluginConfig(plugin) ?? [];
    }
    async registerCompilers(registerCompiler) {
        const cwd = this.dir;
        const hasDependency = (packageName) => this.dependencies.has(packageName);
        for (const [pluginName, plugin] of PluginEntries) {
            if (!plugin.registerCompilers)
                continue;
            if (this.config[pluginName] === false)
                continue;
            if (this.options.cwd !== this.dir && plugin.isRootOnly)
                continue;
            await plugin.registerCompilers({ cwd, dependencies: this.allDependencies, hasDependency, registerCompiler });
        }
    }
    async resolveSourceMaps() {
        const options = {
            cwd: this.dir,
            rootCwd: this.options.cwd,
            manifest: this.manifest,
            rootManifest: this.rootManifest,
            dependencies: this.dependencies,
        };
        const pairs = [];
        for (const pluginName of this.enabledPlugins) {
            const plugin = Plugins[pluginName];
            if (!plugin.resolveSourceMap)
                continue;
            for (const pair of await plugin.resolveSourceMap(options))
                pairs.push(pair);
        }
        return pairs;
    }
    registerVisitors(options) {
        for (const pluginName of this.enabledPlugins) {
            if (options.registeredPlugins.has(pluginName))
                continue;
            const plugin = Plugins[pluginName];
            if (plugin.registerVisitors) {
                options.registeredPlugins.add(pluginName);
                plugin.registerVisitors(options);
            }
        }
    }
    async runPlugins() {
        const wsName = this.name;
        const cwd = this.dir;
        const rootCwd = this.options.cwd;
        const manifest = this.manifest;
        const containingFilePath = join(cwd, 'package.json');
        const isProduction = this.options.isProduction;
        const rootManifest = this.rootManifest;
        const getManifest = this.getManifest;
        const baseOptions = { manifest, rootManifest, cwd, rootCwd, containingFilePath, getManifest };
        const baseScriptOptions = { ...baseOptions, isProduction, enabledPlugins: this.enabledPlugins, getScriptCommands };
        const [productionScripts, developmentScripts] = getFilteredScripts(manifest.scripts ?? {});
        const inputsFromManifest = _getInputsFromScripts(Object.values(developmentScripts), baseOptions);
        const productionInputsFromManifest = _getInputsFromScripts(Object.values(productionScripts), baseOptions);
        for (const input of productionInputsFromManifest)
            input.production = true;
        const createGetInputsFromScripts = (containingFilePath) => (scripts, options) => _getInputsFromScripts(scripts, { ...baseOptions, ...options, containingFilePath });
        const inputs = [];
        const configFilesMap = this.configFilesMap;
        const seen = new Map();
        const parsedConfigCache = new Map();
        const getSeenConfigFiles = (pluginName) => {
            let configFilePaths = seen.get(pluginName);
            if (!configFilePaths) {
                configFilePaths = new Set();
                seen.set(pluginName, configFilePaths);
            }
            return configFilePaths;
        };
        const storeConfigFilePath = (pluginName, input) => {
            const configFilePath = this.handleInput(input);
            if (configFilePath) {
                const workspace = this.findWorkspaceByFilePath(configFilePath);
                if (workspace) {
                    const name = this.name === ROOT_WORKSPACE_NAME ? workspace.name : this.name;
                    if (name === wsName && seen.get(pluginName)?.has(configFilePath))
                        return;
                    let configFiles = configFilesMap.get(name);
                    if (!configFiles) {
                        configFiles = new Map();
                        configFilesMap.set(name, configFiles);
                    }
                    let configFilePaths = configFiles.get(pluginName);
                    if (!configFilePaths) {
                        configFilePaths = new Set();
                        configFiles.set(pluginName, configFilePaths);
                    }
                    configFilePaths.add(configFilePath);
                }
            }
        };
        for (const input of [...inputsFromManifest, ...productionInputsFromManifest]) {
            const inputContainingFilePath = input.containingFilePath ?? containingFilePath;
            if (isConfig(input)) {
                storeConfigFilePath(input.pluginName, { ...input, containingFilePath: inputContainingFilePath });
            }
            else if (isProduction && isEntry(input) && !isDynamicPattern(input.specifier)) {
                inputs.push({ ...input, type: 'deferResolveEntry', containingFilePath: inputContainingFilePath });
            }
            else {
                inputs.push({ ...input, containingFilePath: inputContainingFilePath });
            }
        }
        const runPlugin = async (pluginName, patterns, isResolvedConfigFiles = false) => {
            const plugin = Plugins[pluginName];
            const config = this.getConfigForPlugin(pluginName);
            if (!config)
                return [];
            const inputs = [];
            const seenConfigFiles = getSeenConfigFiles(pluginName);
            const addInput = (input, containingFilePath = input.containingFilePath) => {
                if (isConfig(input)) {
                    storeConfigFilePath(input.pluginName, { ...input, containingFilePath });
                }
                else {
                    inputs.push(Object.assign(input, { containingFilePath }));
                }
            };
            const label = 'config file';
            const configFilePaths = await _glob({ patterns, cwd: rootCwd, dir: cwd, gitignore: false, label });
            if (isResolvedConfigFiles) {
                const foundConfigFilePaths = new Set(configFilePaths);
                for (const filePath of patterns) {
                    if (!foundConfigFilePaths.has(filePath))
                        seenConfigFiles.add(filePath);
                }
            }
            const options = {
                ...baseScriptOptions,
                pluginName,
                config,
                configFilePath: containingFilePath,
                configFileDir: cwd,
                configFileName: '',
                isResolvedConfigFile: isResolvedConfigFiles,
                getInputsFromScripts: createGetInputsFromScripts(containingFilePath),
            };
            if (config.entry) {
                const entryOptions = isProduction && plugin.production?.length ? { production: true } : undefined;
                for (const id of config.entry)
                    inputs.push(toEntry(id, entryOptions));
            }
            else if ((!plugin.resolveConfig && !plugin.resolveFromAST) ||
                (!configFilePaths.some(path => basename(path) !== 'package.json') &&
                    (!this.configFilesMap.get(wsName)?.get(pluginName) ||
                        this.configFilesMap.get(wsName)?.get(pluginName)?.size === 0))) {
                if (plugin.entry)
                    for (const id of plugin.entry)
                        inputs.push(toEntry(id));
                if (plugin.production)
                    for (const id of plugin.production)
                        inputs.push(toEntry(id, { production: true }));
            }
            if (typeof plugin.setup === 'function')
                await plugin.setup();
            for (const configFilePath of configFilePaths) {
                if (seenConfigFiles.has(configFilePath))
                    continue;
                seenConfigFiles.add(configFilePath);
                this.configurationFiles?.paths.add(configFilePath);
                const isManifest = basename(configFilePath) === 'package.json';
                const fd = isManifest ? undefined : this.cache.getFileDescriptor(configFilePath);
                const data = fd?.changed ? undefined : fd?.meta?.data?.[pluginName];
                if (data) {
                    if (data.resolveConfig)
                        for (const id of data.resolveConfig)
                            addInput(id, configFilePath);
                    if (data.resolveFromAST)
                        for (const id of data.resolveFromAST)
                            addInput(id, configFilePath);
                    if (data.configFile)
                        addInput(data.configFile);
                    continue;
                }
                let parsed;
                if (!isManifest && (!plugin.parseConfig || plugin.resolveFromAST)) {
                    if (parsedConfigCache.has(configFilePath)) {
                        parsed = parsedConfigCache.get(configFilePath);
                    }
                    else {
                        const sourceText = this.readRawFile(configFilePath);
                        parsed = sourceText ? _parseFile(configFilePath, sourceText) : undefined;
                        parsedConfigCache.set(configFilePath, parsed);
                    }
                }
                const resolveOpts = {
                    ...options,
                    getInputsFromScripts: createGetInputsFromScripts(configFilePath),
                    configFilePath,
                    configFileDir: dirname(configFilePath),
                    configFileName: basename(configFilePath),
                };
                const cache = {};
                let hasLoadConfigError = false;
                if (plugin.resolveConfig) {
                    if (!plugin.parseConfig && parsed && isExternalReExportsOnly(parsed)) {
                        cache.resolveConfig = [];
                    }
                    if (!cache.resolveConfig) {
                        const isLoad = typeof plugin.isLoadConfig === 'function' ? plugin.isLoadConfig(resolveOpts, this.dependencies) : true;
                        if (isLoad) {
                            const resolveConfig = plugin.resolveConfig;
                            try {
                                const inputs = await trackConfigLoad(configFilePath, this.cache, async () => {
                                    const localConfig = await loadConfigForPlugin(configFilePath, plugin, resolveOpts, pluginName);
                                    return localConfig ? await resolveConfig(localConfig, resolveOpts) : undefined;
                                });
                                if (inputs) {
                                    if (plugin.isFilterTransitiveDependencies && !isManifest) {
                                        filterTransitiveDependencies(inputs, configFilePath, this.readRawFile);
                                    }
                                    for (const input of inputs)
                                        addInput(input, configFilePath);
                                    cache.resolveConfig = inputs;
                                }
                            }
                            catch (error) {
                                hasLoadConfigError = true;
                                const relPath = toRelative(configFilePath, this.options.cwd);
                                const cause = formatCauseMessage(error instanceof Error ? error : new Error(String(error)), this.options.cwd);
                                if (plugin.isLoadConfigOptional) {
                                    debugLog(wsName, `Error loading ${relPath} (${cause})`);
                                }
                                else {
                                    this.handleConfigLoadError();
                                    logError(`Error loading ${relPath} (${cause})`);
                                    logError('Please fix or visit https://knip.dev/reference/known-issues');
                                }
                            }
                        }
                    }
                }
                if (plugin.resolveFromAST && parsed) {
                    const resolveASTOpts = { ...resolveOpts, readFile: this.readRawFile };
                    const inputs = plugin.resolveFromAST(parsed.program, resolveASTOpts);
                    for (const input of inputs)
                        addInput(input, configFilePath);
                    cache.resolveFromAST = inputs;
                }
                if (!isManifest) {
                    if (extname(configFilePath)) {
                        inputs.push(toEntry(configFilePath));
                        cache.configFile = toEntry(configFilePath);
                    }
                    if (hasLoadConfigError || hasUnhandledRejection()) {
                        this.cache.removeEntry(configFilePath);
                    }
                    else if (fd?.meta) {
                        fd.meta.data = { ...fd.meta.data, [pluginName]: cache };
                    }
                }
            }
            if (plugin.resolve) {
                const dependencies = (await plugin.resolve(options)) ?? [];
                for (const id of dependencies)
                    addInput(id, id.containingFilePath ?? containingFilePath);
            }
            if (inputs.some(input => input.specifier.startsWith('!'))) {
                for (const input of inputs)
                    if (!seenConfigFiles.has(input.specifier))
                        input.group = pluginName;
            }
            return inputs;
        };
        const enabledPluginTitles = this.enabledPlugins.map(name => Plugins[name].title);
        debugLogObject(this.name, 'Enabled plugins', enabledPluginTitles);
        for (const pluginName of this.enabledPlugins) {
            const configFiles = this.configFilesMap.get(wsName);
            const patterns = [...this.getConfigurationFilePatterns(pluginName), ...(configFiles?.get(pluginName) ?? [])];
            this.configurationFiles?.addPatterns(this.dir, compact(patterns));
            configFiles?.delete(pluginName);
            for (const input of await runPlugin(pluginName, compact(patterns)))
                inputs.push(input);
        }
        {
            const configFiles = this.configFilesMap.get(wsName);
            if (configFiles) {
                while (configFiles.size > 0) {
                    const entry = configFiles.entries().next().value;
                    if (!entry)
                        break;
                    const [pluginName, dependencies] = entry;
                    configFiles.delete(pluginName);
                    if (this.config[pluginName] === false) {
                        for (const id of dependencies)
                            inputs.push(toEntry(id));
                        continue;
                    }
                    const seenConfigFiles = getSeenConfigFiles(pluginName);
                    const unprocessed = [];
                    for (const filePath of dependencies) {
                        if (!seenConfigFiles.has(filePath))
                            unprocessed.push(filePath);
                    }
                    if (unprocessed.length > 0) {
                        for (const input of await runPlugin(pluginName, unprocessed, true))
                            inputs.push(input);
                    }
                }
            }
        }
        debugLogArray(wsName, 'Plugin dependencies', () => compact(inputs.map(input => toDebugString(input, rootCwd))));
        return inputs;
    }
    getConfigurationHints(type, patterns, filePaths, includedPaths, compilerExtensions) {
        const hints = [];
        const entries = this.config[type].filter(pattern => !pattern.startsWith('!'));
        const workspaceName = this.name;
        const configKey = this.configKey;
        const hint = (type, identifier) => configKey ? { type, identifier, workspaceName, configKey } : { type, identifier, workspaceName };
        const userDefinedPatterns = entries.filter(id => !isDefaultPattern(type, id));
        if (userDefinedPatterns.length === 0)
            return hints;
        if (filePaths.length === 0) {
            for (const pattern of userDefinedPatterns) {
                hints.push(hint(`${type}-empty`, pattern.replace(/!$/, '')));
            }
            return hints;
        }
        const dir = this.dir;
        const relativePaths = [];
        const hasMatch = (isMatch) => {
            for (let i = 0; i < filePaths.length; i++) {
                if (isMatch((relativePaths[i] ??= relative(dir, filePaths[i]))))
                    return true;
            }
            return false;
        };
        for (const pattern of patterns) {
            if (pattern.startsWith('!'))
                continue;
            const id = pattern.replace(/!$/, '');
            if ((hasNoProductionSuffix(pattern) && patterns.includes(`${pattern}!`)) || includedPaths.has(join(dir, id))) {
                hints.push(hint(`${type}-redundant`, pattern));
            }
            else if (!hasMatch(picomatch(id))) {
                hints.push(hint(`${type}-empty`, pattern));
            }
        }
        if (type === 'project' && compilerExtensions) {
            const seen = new Set();
            const patternExtensions = new Set();
            for (const pattern of userDefinedPatterns) {
                for (const ext of extractPatternExtensions(pattern)) {
                    patternExtensions.add(ext);
                    if (seen.has(ext) || DEFAULT_EXTENSIONS.has(ext) || compilerExtensions.has(ext))
                        continue;
                    seen.add(ext);
                    hints.push(hint('project-extension-unregistered', ext));
                }
            }
            if (patternExtensions.size > 0) {
                for (const ext of compilerExtensions) {
                    if (patternExtensions.has(ext))
                        continue;
                    hints.push(hint('project-extension-excluded', ext));
                }
            }
        }
        return hints;
    }
    onDispose() {
        this.cache.reconcile();
    }
}
