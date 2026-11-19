import type { CatalogCounselor } from '../CatalogCounselor.ts';
import type { ConfigurationChief } from '../ConfigurationChief.ts';
import type { ConsoleStreamer } from '../ConsoleStreamer.ts';
import type { DependencyDeputy } from '../DependencyDeputy.ts';
import type { IssueCollector } from '../IssueCollector.ts';
import type { ModuleGraph } from '../types/module-graph.ts';
import type { MainOptions } from '../util/create-options.ts';
import type { SubpathReferences } from './SubpathReferences.ts';
interface AnalyzeOptions {
    analyzedFiles: Set<string>;
    counselor: CatalogCounselor;
    chief: ConfigurationChief;
    collector: IssueCollector;
    deputy: DependencyDeputy;
    entryPaths: Set<string>;
    graph: ModuleGraph;
    isGitIgnored: (filePath: string) => boolean;
    streamer: ConsoleStreamer;
    subpathReferences: SubpathReferences;
    unreferencedFiles: Set<string>;
    options: MainOptions;
}
export declare const analyze: ({ analyzedFiles, counselor, chief, collector, deputy, entryPaths, graph, isGitIgnored, streamer, subpathReferences, unreferencedFiles, options, }: AnalyzeOptions) => Promise<() => Promise<void>>;
export {};
