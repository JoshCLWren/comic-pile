import type { ConfigurationHint } from './types/issues.ts';
export type UnusedIgnorePattern = {
    hints: ConfigurationHint[];
    isMatch: (path: string) => boolean;
};
interface ReasonContext {
    cwd: string;
    filePaths: Iterable<string>[];
    isGitIgnored: (filePath: string) => boolean;
}
interface SettleContext {
    countWorkspaces: (configKey: string) => number;
}
export declare const getUnusedIgnorePatternHints: (patterns: UnusedIgnorePattern[], context: ReasonContext) => ConfigurationHint[];
export declare const settleConfigurationHints: (candidates: Iterable<ConfigurationHint>, context: SettleContext) => ConfigurationHint[];
export {};
