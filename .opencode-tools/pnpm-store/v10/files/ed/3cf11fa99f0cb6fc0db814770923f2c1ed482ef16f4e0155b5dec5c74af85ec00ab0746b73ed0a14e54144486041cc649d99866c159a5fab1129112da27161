import { createScriptParserContext } from './binaries/create-script-parser-context.js';
import { _getInputsFromScripts } from './binaries/index.js';
import { CatalogCounselor } from './CatalogCounselor.js';
import { ConfigurationChief } from './ConfigurationChief.js';
import { ConsoleStreamer } from './ConsoleStreamer.js';
import { DependencyDeputy } from './DependencyDeputy.js';
import { analyze } from './graph/analyze.js';
import { build } from './graph/build.js';
import { SubpathReferences } from './graph/SubpathReferences.js';
import { IssueCollector } from './IssueCollector.js';
import { ProjectPrincipal } from './ProjectPrincipal.js';
import { debugLogObject } from './util/debug.js';
import { flushGitignoreCache, initGitignoreCache } from './util/gitignore-cache.js';
import { flushGlobCache, initGlobCache } from './util/glob-cache.js';
import { getGitIgnoredHandler } from './util/glob-core.js';
import { isCatalog } from './util/input.js';
import { createManifest } from './util/package-json.js';
import { getModuleSourcePathHandler, getWorkspacePackageTargetHandler } from './util/to-source-path.js';
import { clearResolverCache } from './util/resolve.js';
import { getSessionHandler } from './util/watch.js';
export const run = async (options) => {
    debugLogObject('*', 'Unresolved configuration', options);
    debugLogObject('*', 'Included issue types', options.includedIssueTypes);
    clearResolverCache();
    if (options.isCache) {
        initGlobCache(options.cacheLocation);
        initGitignoreCache(options.cacheLocation);
    }
    const chief = new ConfigurationChief(options);
    const deputy = new DependencyDeputy(options);
    const streamer = new ConsoleStreamer(options);
    const collector = new IssueCollector(options);
    const counselor = new CatalogCounselor(options);
    streamer.cast('Reading workspace configuration');
    const workspaces = await chief.getWorkspaces();
    const includedWorkspaceNames = new Set(workspaces.map(workspace => workspace.name));
    const scriptParserContext = createScriptParserContext(chief);
    const { rootManifest, getManifest } = scriptParserContext;
    for (const name of chief.availableWorkspaceNames) {
        const workspace = chief.workspacePackages.get(name);
        if (!workspace)
            continue;
        counselor.addWorkspace(workspace);
        if (includedWorkspaceNames.has(name))
            continue;
        const manifest = createManifest(workspace.manifest);
        const inputs = _getInputsFromScripts(Object.values(manifest.scripts ?? {}), {
            cwd: workspace.dir,
            rootCwd: options.cwd,
            containingFilePath: workspace.manifestPath,
            manifest,
            rootManifest,
            getManifest,
        });
        for (const input of inputs) {
            if (isCatalog(input)) {
                counselor.addReference({ catalogName: input.catalogName, packageName: input.specifier });
            }
        }
    }
    const isGitIgnored = await getGitIgnoredHandler(options, new Set(workspaces.map(w => w.dir)));
    const toSourceFilePath = getModuleSourcePathHandler(chief);
    const findWorkspacePackageTarget = getWorkspacePackageTargetHandler(chief);
    const principal = new ProjectPrincipal(options, toSourceFilePath, findWorkspacePackageTarget, filePath => chief.findWorkspaceByFilePath(filePath)?.name);
    const subpathReferences = new SubpathReferences({
        chief,
        principal,
        workspaces,
        findWorkspacePackageTarget,
        isGitIgnored,
    });
    collector.setWorkspaceFilter(chief.workspaceFilePathFilter);
    collector.setSelectedWorkspaces(chief.selectedWorkspaces);
    collector.setIgnoreIssues(chief.getIgnoreIssues());
    debugLogObject('*', 'Included workspaces', () => workspaces.map(w => w.pkgName));
    debugLogObject('*', 'Included workspace configs', () => workspaces.map(w => ({ pkgName: w.pkgName, name: w.name, config: w.config, ancestors: w.ancestors })));
    const { graph, entryPaths, analyzedFiles, unreferencedFiles, analyzeSourceFile, enabledPluginsStore, configurationFiles, } = await build({
        chief,
        collector,
        counselor,
        deputy,
        principal,
        isGitIgnored,
        scriptParserContext,
        streamer,
        subpathReferences,
        workspaces,
        options,
    });
    const reAnalyze = await analyze({
        analyzedFiles,
        counselor,
        chief,
        collector,
        deputy,
        entryPaths,
        graph,
        isGitIgnored,
        streamer,
        subpathReferences,
        unreferencedFiles,
        options,
    });
    let session;
    if (options.isSession) {
        const isIgnored = (filePath) => (!!options.cacheLocation && filePath.startsWith(options.cacheLocation)) ||
            filePath.includes('/.git/') ||
            isGitIgnored(filePath);
        session = await getSessionHandler(options, {
            analyzedFiles,
            analyzeSourceFile,
            subpathReferences,
            chief,
            collector,
            analyze: reAnalyze,
            principal,
            graph,
            configurationFiles,
            isIgnored,
            unreferencedFiles,
            entryPaths,
        });
    }
    const { issues, counters, tagHints, configurationHints, hasConfigLoadErrors } = collector.getIssues();
    if (!options.isWatch)
        streamer.clear();
    if (options.isCache) {
        flushGlobCache();
        flushGitignoreCache();
    }
    return {
        results: {
            issues,
            counters,
            tagHints,
            configurationHints,
            hasConfigLoadErrors,
            selectedWorkspaces: chief.selectedWorkspaces ? Array.from(chief.selectedWorkspaces) : undefined,
            includedWorkspaceDirs: Array.from(chief.workspacesByDir.keys()),
            enabledPlugins: Object.fromEntries(enabledPluginsStore),
        },
        session,
        streamer,
    };
};
