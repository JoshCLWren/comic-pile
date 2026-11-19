import type { Results } from '../../run.ts';
import type { ConfigurationHint, ConfigurationHintType, ReporterOptions, UnusedIgnorePatternReason } from '../../types/issues.ts';
interface PrintHintOptions {
    type: ConfigurationHintType;
    identifier: string | RegExp;
    filePath: string;
    configFilePath?: string;
    workspaceName?: string;
    configKey?: string;
    reason?: UnusedIgnorePatternReason;
    size?: number;
}
export declare const hintPrinters: Map<ConfigurationHintType, {
    print: (options: PrintHintOptions) => string;
}>;
interface ProcessedHint extends ConfigurationHint {
    message: string;
}
export declare const finalizeConfigurationHints: (results: Results, options: {
    cwd: string;
    configFilePath?: string;
}) => ProcessedHint[];
export declare const printConfigurationHints: ({ cwd, counters, issues, tagHints, configurationHints, hasConfigLoadErrors, enabledPlugins, isTreatConfigHintsAsErrors, includedWorkspaceDirs, selectedWorkspaces, configFilePath, }: ReporterOptions) => void;
export declare const printTagHints: ({ cwd, tagHints, isTreatTagHintsAsErrors }: ReporterOptions) => void;
export {};
