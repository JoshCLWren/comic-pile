import { ISSUE_TYPES, SYMBOL_TYPE } from '../constants.js';
import { ConfigurationValidationError } from './errors.js';
import { isPluginName } from './is-plugin-name.js';
import { timerify } from './Performance.js';
import { checkArray, checkBoolean, checkObject, checkRecord, checkString, invalid, isObject, } from './validation.js';
const checkStrings = checkArray(checkString);
const checkGlob = (value, path, errors) => typeof value === 'string' || checkStrings(value, path, errors);
const checkPattern = (value, path, errors) => typeof value === 'string' || value instanceof RegExp || invalid(path, errors);
const issueTypes = new Set(ISSUE_TYPES);
const isIssueType = (value) => typeof value === 'string' && issueTypes.has(value);
const checkIssueType = (value, path, errors) => isIssueType(value) || invalid(path, errors);
const checkSeverity = (value, path, errors) => value === 'error' || value === 'warn' || value === 'off' || invalid(path, errors);
const symbolFields = {};
for (const type of Object.values(SYMBOL_TYPE))
    if (type !== 'unknown')
        symbolFields[type] = checkBoolean;
const checkIgnoreExports = (value, path, errors) => typeof value === 'boolean' || checkObject(value, path, errors, symbolFields);
const pluginFields = { config: checkGlob, entry: checkGlob, project: checkGlob };
const checkPlugin = (value, path, errors) => typeof value === 'boolean' ||
    (isObject(value) ? checkObject(value, path, errors, pluginFields, 'ignore') : checkGlob(value, path, errors));
const getPluginCheck = (key) => (isPluginName(key) ? checkPlugin : undefined);
const checkPatterns = checkArray(checkPattern);
const checkIssueTypes = checkArray(checkIssueType);
const workspaceFields = {
    entry: checkGlob,
    project: checkGlob,
    paths: checkRecord(checkStrings),
    ignore: checkGlob,
    ignoreFiles: checkGlob,
    ignoreBinaries: checkPatterns,
    ignoreGlobalBinaries: checkBoolean,
    ignoreDependencies: checkPatterns,
    ignoreMembers: checkPatterns,
    ignoreUnresolved: checkPatterns,
    ignoreExportsUsedInFile: checkIgnoreExports,
    ignoreIssues: checkRecord(checkIssueTypes),
    includeEntryExports: checkBoolean,
    includeSubpathExports: checkBoolean,
};
const checkWorkspace = (value, path, errors) => checkObject(value, path, errors, workspaceFields, getPluginCheck);
const cycleFields = { allow: checkArray(checkStrings), dynamicImports: checkBoolean };
const checkCompilers = checkRecord((_value) => true);
const rootFields = {
    $schema: checkString,
    rules: checkRecord(checkSeverity, isIssueType),
    ...workspaceFields,
    cycles: (value, path, errors) => checkObject(value, path, errors, cycleFields),
    ignoreWorkspaces: checkStrings,
    compilers: checkCompilers,
    asyncCompilers: checkCompilers,
    tags: checkStrings,
    treatConfigHintsAsErrors: checkBoolean,
    treatTagHintsAsErrors: checkBoolean,
    preprocessor: checkGlob,
    preprocessorOptions: checkRecord((_value) => true),
    include: checkIssueTypes,
    exclude: checkIssueTypes,
    workspaces: checkRecord(checkWorkspace),
};
const checkConfiguration = (value, path, errors) => checkObject(value, path, errors, rootFields, getPluginCheck);
export const parseConfiguration = timerify((value) => {
    const errors = [];
    if (!checkConfiguration(value, '', errors))
        throw new ConfigurationValidationError(errors);
    return value;
}, 'parseConfiguration');
