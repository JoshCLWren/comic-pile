import { _load } from './loader.js';
export const toReporterOptions = (options, results, args) => ({
    ...results,
    report: options.includedIssueTypes,
    cwd: options.cwd,
    configFilePath: options.configFilePath,
    isDisableConfigHints: options.isDisableConfigHints,
    isDisableTagHints: options.isDisableTagHints,
    isProduction: options.isProduction,
    isShowProgress: options.isShowProgress,
    isTreatConfigHintsAsErrors: options.isTreatConfigHintsAsErrors,
    isTreatTagHintsAsErrors: options.isTreatTagHintsAsErrors,
    maxShowIssues: options.maxShowIssues,
    options: args?.['reporter-options'] ?? '',
    preprocessorOptions: options.preprocessorOptions,
});
export const createPreprocessor = async (processors) => {
    const preprocessors = await Promise.all(processors.map(_load));
    return async (data) => {
        for (const preprocessor of preprocessors)
            data = await preprocessor(data);
        return data;
    };
};
