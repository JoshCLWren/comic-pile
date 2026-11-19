const nearOperationFilePresetNames = new Set([
    'near-operation-file',
    'near-operation-file-preset',
    '@graphql-codegen/near-operation-file-preset',
]);
export const isNearOperationFilePreset = (preset) => typeof preset === 'string' && nearOperationFilePresetNames.has(preset);
export function isConfigurationOutput(config) {
    return 'preset' in config || 'plugins' in config;
}
export const isGraphqlConfigTypes = (config) => {
    return 'extensions' in config;
};
export const isGraphqlProjectsConfigTypes = (config) => {
    return 'projects' in config;
};
