import type { ScriptParserContext } from '../binaries/create-script-parser-context.ts';
import type { CatalogCounselor } from '../CatalogCounselor.ts';
import { type ConfigurationChief, type Workspace } from '../ConfigurationChief.ts';
import type { ConsoleStreamer } from '../ConsoleStreamer.ts';
import type { DependencyDeputy } from '../DependencyDeputy.ts';
import type { IssueCollector } from '../IssueCollector.ts';
import type { ProjectPrincipal } from '../ProjectPrincipal.ts';
import type { ModuleGraph } from '../types/module-graph.ts';
import type { MainOptions } from '../util/create-options.ts';
import { ConfigurationFiles } from '../session/configuration.ts';
import type { SubpathReferences } from './SubpathReferences.ts';
interface BuildOptions {
    chief: ConfigurationChief;
    collector: IssueCollector;
    counselor: CatalogCounselor;
    deputy: DependencyDeputy;
    principal: ProjectPrincipal;
    isGitIgnored: (path: string) => boolean;
    scriptParserContext: ScriptParserContext;
    streamer: ConsoleStreamer;
    subpathReferences: SubpathReferences;
    workspaces: Workspace[];
    options: MainOptions;
}
export declare const build: ({ chief, collector, counselor, deputy, principal, isGitIgnored, scriptParserContext, streamer, subpathReferences, workspaces, options, }: BuildOptions) => Promise<{
    graph: ModuleGraph;
    configurationFiles: ConfigurationFiles | undefined;
    entryPaths: Set<string>;
    analyzedFiles: Set<string>;
    unreferencedFiles: Set<string>;
    analyzeSourceFile: (filePath: string) => Promise<void>;
    enabledPluginsStore: Map<string, string[]>;
}>;
export {};
