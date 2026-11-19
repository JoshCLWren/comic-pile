import { DT_SCOPE, IGNORE_DEFINITELY_TYPED, IGNORED_DEPENDENCIES, IGNORED_RUNTIME_DEPENDENCIES, PROTOCOL_CLOUDFLARE, ROOT_WORKSPACE_NAME, } from './constants.js';
import { getDependencyMetaData } from './manifest/index.js';
import { PackagePeeker } from './PackagePeeker.js';
import { getDefinitelyTypedFor, getPackageFromDefinitelyTyped, getPackageNameFromModuleSpecifier, isBuiltin, isDefinitelyTyped, } from './util/modules.js';
import { findMatch, toRegexOrString } from './util/regex.js';
const filterIsProduction = (id, isProduction) => typeof id === 'string' ? (isProduction || !id.endsWith('!') ? id.replace(/!$/, '') : undefined) : id;
const toIgnoreMap = (items, toId = id => id) => {
    const ids = new Set();
    const ignores = new Map();
    for (const item of items) {
        const id = toId(item.value);
        if (id === undefined || ids.has(id))
            continue;
        ids.add(id);
        ignores.set(toRegexOrString(id), item.configKey);
    }
    return ignores;
};
export class DependencyDeputy {
    isProduction;
    isStrict;
    isReportDependencies;
    _manifests = new Map();
    workspacePkgNames = new Set();
    referencedDependencies;
    hostDependencies;
    installedBinaries;
    hasTypesIncluded;
    rootIgnores;
    constructor({ isProduction, isStrict, isReportDependencies }) {
        this.isProduction = isProduction;
        this.isStrict = isStrict;
        this.isReportDependencies = isReportDependencies;
        this.referencedDependencies = new Map();
        this.hostDependencies = new Map();
        this.installedBinaries = new Map();
        this.hasTypesIncluded = new Map();
    }
    toWorkspaceIgnores({ ignoreDependencies, ignoreBinaries, ignoreUnresolved }) {
        const toId = (id) => filterIsProduction(id, this.isProduction);
        const ignoreConfigKeys = {
            ignoreDependencies: toIgnoreMap(ignoreDependencies, toId),
            ignoreBinaries: toIgnoreMap(ignoreBinaries, toId),
            ignoreUnresolved: toIgnoreMap(ignoreUnresolved),
        };
        return {
            ignoreDependencies: [...ignoreConfigKeys.ignoreDependencies.keys()],
            ignoreBinaries: [...ignoreConfigKeys.ignoreBinaries.keys()],
            ignoreUnresolved: [...ignoreConfigKeys.ignoreUnresolved.keys()],
            unusedIgnoreDependencies: new Set(ignoreConfigKeys.ignoreDependencies.keys()),
            unusedIgnoreBinaries: new Set(ignoreConfigKeys.ignoreBinaries.keys()),
            unusedIgnoreUnresolved: new Set(ignoreConfigKeys.ignoreUnresolved.keys()),
            ignoreConfigKeys,
        };
    }
    addWorkspace({ name, dir, manifestPath, manifestStr, manifest, ...ignores }) {
        const dependencies = Object.keys(manifest.dependencies ?? {});
        const peerDependencies = Object.keys(manifest.peerDependencies ?? {});
        const optionalDependencies = Object.keys(manifest.optionalDependencies ?? {});
        const optionalPeerDependencies = new Set();
        if (manifest.peerDependenciesMeta) {
            for (const dep of peerDependencies) {
                if (manifest.peerDependenciesMeta[dep]?.optional)
                    optionalPeerDependencies.add(dep);
            }
        }
        const requiredPeerDependencies = peerDependencies.filter(dep => !optionalPeerDependencies.has(dep));
        const devDependencies = Object.keys(manifest.devDependencies ?? {});
        const allDependencies = [...dependencies, ...devDependencies, ...peerDependencies, ...optionalDependencies];
        const uninstalledOptionalDependencies = new Set();
        const packageNames = [
            ...dependencies,
            ...peerDependencies,
            ...optionalDependencies,
            ...(this.isProduction ? [] : devDependencies),
        ];
        if (this.isReportDependencies) {
            const { hostDependencies, installedBinaries, hasTypesIncluded, uninstalledDependencies } = getDependencyMetaData({
                packageNames,
                dir,
            });
            this.setHostDependencies(name, hostDependencies);
            this.installedBinaries.set(name, installedBinaries);
            this.hasTypesIncluded.set(name, hasTypesIncluded);
            for (const dependency of optionalDependencies) {
                if (uninstalledDependencies.has(dependency))
                    uninstalledOptionalDependencies.add(dependency);
            }
        }
        this._manifests.set(name, {
            ...this.toWorkspaceIgnores(ignores),
            workspaceDir: dir,
            manifestPath,
            manifestStr,
            dependencies,
            devDependencies,
            peerDependencies: new Set(peerDependencies),
            optionalPeerDependencies,
            requiredPeerDependencies,
            uninstalledOptionalDependencies,
            allDependencies: new Set(allDependencies),
            engines: manifest.engines ?? {},
            isPrivate: Boolean(manifest.private),
        });
    }
    getWorkspaceManifest(workspaceName) {
        return this._manifests.get(workspaceName);
    }
    setRootIgnores(ignores) {
        this.rootIgnores = this.toWorkspaceIgnores(ignores);
    }
    setWorkspacePkgNames(pkgNames) {
        this.workspacePkgNames = new Set(pkgNames);
    }
    getProductionDependencies(workspaceName) {
        const manifest = this._manifests.get(workspaceName);
        if (!manifest)
            return [];
        if (this.isStrict)
            return [...manifest.dependencies, ...manifest.requiredPeerDependencies];
        return manifest.dependencies;
    }
    getDevDependencies(workspaceName) {
        return this._manifests.get(workspaceName)?.devDependencies ?? [];
    }
    dependencyCache = new Map();
    getDependencies(workspaceName) {
        let deps = this.dependencyCache.get(workspaceName);
        if (deps)
            return deps;
        const manifest = this._manifests.get(workspaceName);
        deps = manifest ? new Set([...manifest.dependencies, ...manifest.devDependencies]) : new Set();
        this.dependencyCache.set(workspaceName, deps);
        return deps;
    }
    getAllDependencies(workspaceName) {
        return this._manifests.get(workspaceName)?.allDependencies ?? new Set();
    }
    addReferencedDependency(workspaceName, packageName) {
        if (!this.referencedDependencies.has(workspaceName)) {
            this.referencedDependencies.set(workspaceName, new Set());
        }
        this.referencedDependencies.get(workspaceName)?.add(packageName);
    }
    addReference(workspaceName, packageName, isDevelopment) {
        if (!this.isProduction || !isDevelopment)
            this.addReferencedDependency(workspaceName, packageName);
    }
    setHostDependencies(workspaceName, hostDependencies) {
        this.hostDependencies.set(workspaceName, hostDependencies);
    }
    getHostDependenciesFor(workspaceName, dependency) {
        return this.hostDependencies.get(workspaceName)?.get(dependency) ?? [];
    }
    getOptionalPeerDependencies(workspaceName) {
        return this._manifests.get(workspaceName)?.optionalPeerDependencies ?? new Set();
    }
    maybeAddReferencedExternalDependency(workspace, packageName, { specifier, isDevOnly, isTypeOnly, isResolved, isPublishedType, isCaught, isDevelopment, }) {
        if (isBuiltin(specifier) || specifier.startsWith(PROTOCOL_CLOUDFLARE))
            return true;
        if (IGNORED_RUNTIME_DEPENDENCIES.has(packageName))
            return true;
        if (packageName === workspace.pkgName)
            return true;
        const optionalPeerDependencies = this.getOptionalPeerDependencies(workspace.name);
        const workspaceNames = this.isStrict ? [workspace.name] : [workspace.name, ...workspace.ancestors.toReversed()];
        const isDevOrTypeOnly = isDevOnly || (isTypeOnly && !isPublishedType);
        const isCaughtOptionalPeer = isCaught && optionalPeerDependencies.has(packageName);
        const closestWorkspaceName = workspaceNames.find(name => this.isInDependencies(name, packageName, isDevOrTypeOnly, isCaughtOptionalPeer));
        const typesPackageName = !isDefinitelyTyped(packageName) && getDefinitelyTypedFor(packageName);
        const closestWorkspaceNameForTypes = typesPackageName && workspaceNames.find(name => this.isInDependencies(name, typesPackageName, isDevOrTypeOnly));
        if (closestWorkspaceNameForTypes && !this.hasTypesIncluded.get(closestWorkspaceNameForTypes)?.has(packageName))
            this.addReference(closestWorkspaceNameForTypes, typesPackageName, isDevelopment);
        if (closestWorkspaceName) {
            this.addReference(closestWorkspaceName, packageName, isDevelopment);
            return true;
        }
        if (closestWorkspaceNameForTypes && isTypeOnly)
            return true;
        if (this._manifests.get(workspace.name)?.engines[packageName])
            return true;
        if (!this.isStrict && this.workspacePkgNames.has(packageName) && this._manifests.get(workspace.name)?.isPrivate) {
            this.addReference(workspace.name, packageName, isDevelopment);
            return true;
        }
        if (!this.isStrict && isResolved !== false) {
            for (const name of workspaceNames) {
                const hosts = this.getHostDependenciesFor(name, packageName);
                if (hosts.length === 0)
                    continue;
                const m = this._manifests.get(name);
                if (m && hosts.some(h => m.allDependencies.has(h.name))) {
                    this.addReference(name, packageName, isDevelopment);
                    return true;
                }
            }
        }
        this.addReference(workspace.name, packageName, isDevelopment);
        return false;
    }
    maybeAddReferencedBinary(workspace, binaryName, isDevelopment) {
        if (!this.isReportDependencies)
            return new Set();
        const workspaceNames = this.isStrict ? [workspace.name] : [workspace.name, ...workspace.ancestors.toReversed()];
        for (const name of workspaceNames) {
            const binaries = this.installedBinaries.get(name);
            if (binaries?.has(binaryName)) {
                const dependencies = binaries.get(binaryName);
                if (dependencies?.size) {
                    for (const dependency of dependencies)
                        this.addReference(name, dependency, isDevelopment);
                    return dependencies;
                }
            }
        }
        const optionalDependencies = new Set();
        for (const name of workspaceNames) {
            const manifest = this._manifests.get(name);
            if (!manifest)
                continue;
            for (const dependency of manifest.uninstalledOptionalDependencies) {
                const defaultBinaryName = dependency.replace(/^@[^/]+\//, '');
                if (defaultBinaryName === binaryName) {
                    optionalDependencies.add(dependency);
                    this.addReference(name, dependency, isDevelopment);
                }
            }
        }
        if (optionalDependencies.size)
            return optionalDependencies;
        return;
    }
    isInDependencies(workspaceName, packageName, isDevOnly, isCaughtOptionalPeer) {
        const manifest = this._manifests.get(workspaceName);
        if (!manifest)
            return false;
        if (this.isStrict && !isDevOnly) {
            if (isCaughtOptionalPeer && manifest.optionalPeerDependencies.has(packageName))
                return true;
            return this.getProductionDependencies(workspaceName).includes(packageName);
        }
        return manifest.allDependencies.has(packageName);
    }
    settleDependencyIssues() {
        const dependencyIssues = [];
        const devDependencyIssues = [];
        const optionalPeerDependencyIssues = [];
        for (const [workspace, { manifestPath: filePath, manifestStr }] of this._manifests) {
            const referencedDependencies = this.referencedDependencies.get(workspace);
            const hasTypesIncluded = this.hasTypesIncluded.get(workspace);
            const peeker = new PackagePeeker(manifestStr);
            const isReferencedDependency = (dependency, visited = new Set()) => {
                if (referencedDependencies?.has(dependency))
                    return true;
                if (visited.has(dependency))
                    return false;
                visited.add(dependency);
                const [scope, typedDependency] = dependency.split('/');
                if (scope === DT_SCOPE) {
                    const typedPackageName = getPackageFromDefinitelyTyped(typedDependency);
                    if (IGNORE_DEFINITELY_TYPED.has(typedPackageName))
                        return true;
                    if (hasTypesIncluded?.has(typedPackageName))
                        return false;
                    const hostDependencies = [
                        ...this.getHostDependenciesFor(workspace, dependency),
                        ...this.getHostDependenciesFor(workspace, typedPackageName),
                    ];
                    if (hostDependencies.length)
                        return hostDependencies.some(host => isReferencedDependency(host.name, visited));
                    if (!referencedDependencies?.has(dependency))
                        return false;
                    return referencedDependencies.has(typedPackageName);
                }
                const hostDependencies = this.getHostDependenciesFor(workspace, dependency);
                return hostDependencies.some(hostDependency => isReferencedDependency(hostDependency.name, visited));
            };
            const isNotReferencedDependency = (dependency) => !isReferencedDependency(dependency);
            for (const symbol of this.getProductionDependencies(workspace).filter(isNotReferencedDependency)) {
                const position = peeker.getPropertyLocation('dependencies', symbol) ?? peeker.getPropertyLocation('peerDependencies', symbol);
                dependencyIssues.push({ type: 'dependencies', workspace, filePath, symbol, fixes: [], ...position });
            }
            const manifest = this._manifests.get(workspace);
            for (const symbol of this.getDevDependencies(workspace)) {
                if (!manifest.dependencies.includes(symbol) && !isNotReferencedDependency(symbol))
                    continue;
                const position = peeker.getPropertyLocation('devDependencies', symbol);
                devDependencyIssues.push({ type: 'devDependencies', filePath, workspace, symbol, fixes: [], ...position });
            }
            for (const symbol of this.getOptionalPeerDependencies(workspace)) {
                if (!referencedDependencies?.has(symbol))
                    continue;
                if (manifest.dependencies.includes(symbol) || manifest.devDependencies.includes(symbol))
                    continue;
                const pos = peeker.getPropertyLocation('peerDependencies', symbol);
                optionalPeerDependencyIssues.push({
                    type: 'optionalPeerDependencies',
                    filePath,
                    workspace,
                    symbol,
                    fixes: [],
                    ...pos,
                });
            }
        }
        return { dependencyIssues, devDependencyIssues, optionalPeerDependencyIssues };
    }
    handleIgnoredDependencies(issues, counters, type) {
        for (const key in issues[type]) {
            const issueSet = issues[type][key];
            for (const issueKey in issueSet) {
                const issue = issueSet[issueKey];
                const packageName = getPackageNameFromModuleSpecifier(issue.symbol);
                if (!packageName)
                    continue;
                if (IGNORED_DEPENDENCIES.has(packageName)) {
                    if (type === 'devDependencies') {
                        const manifest = this.getWorkspaceManifest(issue.workspace);
                        if (manifest?.dependencies.includes(packageName))
                            continue;
                    }
                    delete issueSet[issueKey];
                    counters[type]--;
                }
                else {
                    const manifest = this.getWorkspaceManifest(issue.workspace);
                    if (manifest) {
                        const ignoreItem = findMatch(manifest.ignoreDependencies, packageName);
                        if (ignoreItem) {
                            delete issueSet[issueKey];
                            counters[type]--;
                            manifest.unusedIgnoreDependencies.delete(ignoreItem);
                        }
                        else if (issue.workspace !== ROOT_WORKSPACE_NAME) {
                            const manifest = this._manifests.get(ROOT_WORKSPACE_NAME) ?? this.rootIgnores;
                            if (manifest) {
                                const ignoreItem = findMatch(manifest.ignoreDependencies, packageName);
                                if (ignoreItem) {
                                    delete issueSet[issueKey];
                                    counters[type]--;
                                    manifest.unusedIgnoreDependencies.delete(ignoreItem);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    handleIgnoredBinaries(issues, counters, type) {
        for (const key in issues[type]) {
            const issueSet = issues[type][key];
            for (const issueKey in issueSet) {
                const issue = issueSet[issueKey];
                const manifest = this.getWorkspaceManifest(issue.workspace);
                if (manifest) {
                    const ignoreItem = findMatch(manifest.ignoreBinaries, issue.symbol);
                    if (ignoreItem) {
                        delete issueSet[issueKey];
                        counters[type]--;
                        manifest.unusedIgnoreBinaries.delete(ignoreItem);
                    }
                    else {
                        const manifest = this._manifests.get(ROOT_WORKSPACE_NAME) ?? this.rootIgnores;
                        if (manifest) {
                            const ignoreItem = findMatch(manifest.ignoreBinaries, issue.symbol);
                            if (ignoreItem) {
                                delete issueSet[issueKey];
                                counters[type]--;
                                manifest.unusedIgnoreBinaries.delete(ignoreItem);
                            }
                        }
                    }
                }
            }
        }
    }
    handleIgnoredUnresolved(issues, counters) {
        for (const key in issues.unresolved) {
            const issueSet = issues.unresolved[key];
            for (const issueKey in issueSet) {
                const issue = issueSet[issueKey];
                const manifest = this.getWorkspaceManifest(issue.workspace);
                if (manifest) {
                    const ignoreItem = findMatch(manifest.ignoreUnresolved, issue.symbol);
                    if (ignoreItem) {
                        delete issueSet[issueKey];
                        counters.unresolved--;
                        manifest.unusedIgnoreUnresolved.delete(ignoreItem);
                    }
                    else {
                        const manifest = this._manifests.get(ROOT_WORKSPACE_NAME) ?? this.rootIgnores;
                        if (manifest) {
                            const ignoreItem = findMatch(manifest.ignoreUnresolved, issue.symbol);
                            if (ignoreItem) {
                                delete issueSet[issueKey];
                                counters.unresolved--;
                                manifest.unusedIgnoreUnresolved.delete(ignoreItem);
                            }
                        }
                    }
                }
            }
        }
    }
    removeIgnoredIssues({ issues, counters }) {
        this.handleIgnoredDependencies(issues, counters, 'dependencies');
        this.handleIgnoredDependencies(issues, counters, 'devDependencies');
        this.handleIgnoredDependencies(issues, counters, 'optionalPeerDependencies');
        this.handleIgnoredDependencies(issues, counters, 'unlisted');
        this.handleIgnoredDependencies(issues, counters, 'unresolved');
        this.handleIgnoredBinaries(issues, counters, 'binaries');
        this.handleIgnoredUnresolved(issues, counters);
    }
    getConfigurationHints() {
        const configurationHints = [];
        const workspaceIgnores = this.rootIgnores
            ? [...this._manifests, [ROOT_WORKSPACE_NAME, this.rootIgnores]]
            : this._manifests;
        for (const [workspaceName, manifest] of workspaceIgnores) {
            const toHint = (type, identifier) => {
                const configKey = manifest.ignoreConfigKeys[type].get(identifier);
                return configKey ? { workspaceName, identifier, type, configKey } : { workspaceName, identifier, type };
            };
            for (const identifier of manifest.unusedIgnoreDependencies) {
                configurationHints.push(toHint('ignoreDependencies', identifier));
            }
            for (const identifier of manifest.unusedIgnoreBinaries) {
                configurationHints.push(toHint('ignoreBinaries', identifier));
            }
            for (const identifier of manifest.unusedIgnoreUnresolved) {
                configurationHints.push(toHint('ignoreUnresolved', identifier));
            }
        }
        return configurationHints;
    }
    addIgnoredDependencies(workspaceName, identifier) {
        this._manifests.get(workspaceName)?.ignoreDependencies.push(toRegexOrString(identifier));
    }
    addIgnoredBinaries(workspaceName, identifier) {
        this._manifests.get(workspaceName)?.ignoreBinaries.push(toRegexOrString(identifier));
    }
    addIgnoredUnresolved(workspaceName, identifier) {
        this._manifests.get(workspaceName)?.ignoreUnresolved.push(toRegexOrString(identifier));
    }
}
