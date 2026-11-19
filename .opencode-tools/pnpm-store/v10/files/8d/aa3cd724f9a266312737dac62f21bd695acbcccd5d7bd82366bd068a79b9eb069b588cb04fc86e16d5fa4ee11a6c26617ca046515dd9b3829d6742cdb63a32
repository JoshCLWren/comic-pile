import type { Compiler } from '../compilers/types.ts';
import type { CyclesConfig, IgnoreExportsUsedInFile, IgnoreIssues, IgnorePatterns } from './config.ts';
import type { IssueType, Rules } from './issues.ts';
import type { PluginName } from './PluginNames.ts';
type Glob = string | string[];
export type RawPluginConfiguration = boolean | Glob | {
    config?: Glob | undefined;
    entry?: Glob | undefined;
    project?: Glob | undefined;
};
type RawPluginsConfiguration = {
    [K in PluginName]?: RawPluginConfiguration | undefined;
};
export interface RawConfiguration extends RawPluginsConfiguration {
    $schema?: string | undefined;
    rules?: Partial<Rules> | undefined;
    entry?: Glob | undefined;
    project?: Glob | undefined;
    paths?: Record<string, string[]> | undefined;
    ignore?: Glob | undefined;
    ignoreFiles?: Glob | undefined;
    ignoreBinaries?: IgnorePatterns | undefined;
    ignoreGlobalBinaries?: boolean | undefined;
    ignoreDependencies?: IgnorePatterns | undefined;
    ignoreMembers?: IgnorePatterns | undefined;
    ignoreUnresolved?: IgnorePatterns | undefined;
    ignoreExportsUsedInFile?: IgnoreExportsUsedInFile | undefined;
    ignoreIssues?: IgnoreIssues | undefined;
    cycles?: CyclesConfig | undefined;
    ignoreWorkspaces?: string[] | undefined;
    includeEntryExports?: boolean | undefined;
    includeSubpathExports?: boolean | undefined;
    compilers?: Record<string, Compiler | true> | undefined;
    asyncCompilers?: Record<string, Compiler> | undefined;
    tags?: string[] | undefined;
    treatConfigHintsAsErrors?: boolean | undefined;
    treatTagHintsAsErrors?: boolean | undefined;
    preprocessor?: Glob | undefined;
    preprocessorOptions?: Record<string, unknown> | undefined;
    include?: IssueType[] | undefined;
    exclude?: IssueType[] | undefined;
    workspaces?: Record<string, WorkspaceProjectConfig> | undefined;
}
export type WorkspaceProjectConfig = Pick<RawConfiguration, 'entry' | 'project' | 'paths' | 'ignore' | 'ignoreFiles' | 'ignoreBinaries' | 'ignoreGlobalBinaries' | 'ignoreDependencies' | 'ignoreMembers' | 'ignoreUnresolved' | 'ignoreExportsUsedInFile' | 'ignoreIssues' | 'includeEntryExports' | 'includeSubpathExports'> & RawPluginsConfiguration;
export {};
