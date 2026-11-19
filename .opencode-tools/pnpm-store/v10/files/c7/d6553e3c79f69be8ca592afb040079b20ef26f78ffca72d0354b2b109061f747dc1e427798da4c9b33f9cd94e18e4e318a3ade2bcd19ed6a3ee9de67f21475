import type { ConfigurationChief } from '../ConfigurationChief.ts';
import type { SubpathReferences } from '../graph/SubpathReferences.ts';
import type { IssueCollector } from '../IssueCollector.ts';
import type { ProjectPrincipal } from '../ProjectPrincipal.ts';
import type { ConfigurationFiles } from '../session/configuration.ts';
import type { ModuleGraph } from '../types/module-graph.ts';
import type { MainOptions } from './create-options.ts';
export type WatchChange = {
    type: 'added' | 'deleted' | 'modified';
    filePath: string;
};
export type SessionHandler = Awaited<ReturnType<typeof getSessionHandler>>;
type WatchOptions = {
    analyzedFiles: Set<string>;
    analyzeSourceFile: (filePath: string) => Promise<void>;
    subpathReferences: SubpathReferences;
    chief: ConfigurationChief;
    collector: IssueCollector;
    analyze: () => Promise<void>;
    principal: ProjectPrincipal;
    graph: ModuleGraph;
    configurationFiles?: ConfigurationFiles;
    isIgnored: (path: string) => boolean;
    unreferencedFiles: Set<string>;
    entryPaths: Set<string>;
};
export declare const getSessionHandler: (options: MainOptions, { analyzedFiles, analyzeSourceFile, subpathReferences, chief, collector, analyze, principal, graph, configurationFiles, isIgnored, unreferencedFiles, entryPaths, }: WatchOptions) => Promise<{
    handleFileChanges: (changes: WatchChange[]) => Promise<{
        duration: number;
        mem: number;
    } | undefined>;
    getEntryPaths: () => Set<string>;
    getGraph: () => ModuleGraph;
    getIssues: () => {
        issues: import("../types/issues.ts").Issues;
        counters: import("../types/issues.ts").Counters;
        tagHints: Set<import("../types/issues.ts").TagHint>;
        configurationHints: import("../types/issues.ts").ConfigurationHint[];
        hasConfigLoadErrors: boolean;
    };
    configurationFiles: ConfigurationFiles | undefined;
}>;
export {};
