import { get } from '../../util/object.js';
import { toShellCommand } from '../../util/scripts.js';
const title = 'TypeScript Content Mapper';
const enablers = 'This plugin is enabled when `package.json#typescript.contentMapper` is present.';
const isEnabled = ({ manifest }) => Boolean(get(manifest, 'typescript.contentMapper'));
const packageJsonPath = 'typescript.contentMapper';
const config = ['package.json'];
const resolveConfig = ({ exec }, options) => {
    if (!Array.isArray(exec) || exec.some(arg => typeof arg !== 'string'))
        return [];
    return options
        .getInputsFromScripts(toShellCommand(exec))
        .map(input => input.type === 'entry' || input.type === 'deferResolveEntry' ? { ...input, production: true } : input);
};
const plugin = {
    title,
    enablers,
    isEnabled,
    packageJsonPath,
    config,
    resolveConfig,
};
export default plugin;
