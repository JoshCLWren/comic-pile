type PluginConfig<T = unknown> = {
    [key: string]: T;
};
export interface ConfiguredPlugin {
    [name: string]: PluginConfig;
}
type NamedPlugin = string;
type OutputConfig = NamedPlugin | ConfiguredPlugin;
type PresetNamesBase = 'client' | 'near-operation-file' | 'gql-tag-operations' | 'graphql-modules' | 'import-types';
export type PresetNames = `${PresetNamesBase}-preset` | PresetNamesBase;
type OutputPreset = {
    buildGeneratesSection: (options: unknown) => Promise<unknown>;
    prepareDocuments?: (outputFilePath: string, outputSpecificDocuments: unknown) => Promise<unknown>;
};
export interface NearOperationFilePresetConfig {
    baseTypesPath?: string;
    extension?: string;
    fileName?: string;
    filePerOperation?: boolean;
    folder?: string;
    [key: string]: unknown;
}
export declare const isNearOperationFilePreset: (preset: ConfiguredOutput['preset']) => preset is PresetNames;
export declare function isConfigurationOutput(config: ConfiguredOutput | ConfiguredPlugin[]): config is ConfiguredOutput;
export interface ConfiguredOutput {
    plugins?: OutputConfig[];
    preset?: PresetNames | OutputPreset;
    presetConfig?: NearOperationFilePresetConfig;
}
export interface GraphqlCodegenTypes {
    generates: {
        [outputPath: string]: ConfiguredOutput | ConfiguredPlugin[];
    };
}
export declare const isGraphqlConfigTypes: (config: GraphqlCodegenTypes | GraphqlConfigTypes | GraphqlProjectsConfigTypes) => config is GraphqlConfigTypes;
export interface GraphqlConfigTypes {
    extensions?: {
        codegen?: GraphqlCodegenTypes;
    };
}
export declare const isGraphqlProjectsConfigTypes: (config: GraphqlCodegenTypes | GraphqlConfigTypes | GraphqlProjectsConfigTypes) => config is GraphqlProjectsConfigTypes;
export interface GraphqlProjectsConfigTypes {
    projects: {
        [projectName: string]: GraphqlConfigTypes;
    };
}
export {};
