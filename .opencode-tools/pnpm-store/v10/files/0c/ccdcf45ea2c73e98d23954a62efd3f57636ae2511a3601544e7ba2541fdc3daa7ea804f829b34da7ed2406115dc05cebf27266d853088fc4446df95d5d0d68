import { toModule, toEntry } from '../../util/input.js';
import { toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Jasmine';
const enablers = ['jasmine'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['spec/support/jasmine.{json,jsonc,js,cjs,mjs}'];
const defaultSpecFiles = 'spec/**/*[sS]pec.{js,mjs}';
const entry = [defaultSpecFiles, 'spec/helpers/**/*.{js,mjs}'];
const toSpecDirPattern = (specDir, pattern) => {
    const isNegated = pattern.startsWith('!');
    const id = isNegated ? pattern.slice(1) : pattern;
    const resolved = toAbsolute(id, specDir);
    return isNegated ? `!${resolved}` : resolved;
};
const resolveConfig = (localConfig, options) => {
    const specDir = localConfig.spec_dir ?? '';
    const specFiles = localConfig.spec_files?.map(pattern => toSpecDirPattern(specDir, pattern)) ?? [defaultSpecFiles];
    const helpers = localConfig.helpers?.map(pattern => toSpecDirPattern(specDir, pattern)) ?? [];
    const requires = localConfig.requires ?? [];
    const inputs = [];
    for (const id of [...specFiles, ...helpers])
        inputs.push(toEntry(id));
    for (const id of requires)
        inputs.push(toModule(id, { dir: options.cwd }));
    if (localConfig.loader)
        inputs.push(toModule(localConfig.loader, { dir: options.cwd }));
    return inputs;
};
const commands = new Set(['init', 'examples', 'help', 'version']);
const args = {
    boolean: ['color', 'fail-fast', 'list-not-applicable', 'no-color'],
    config: ['config'],
    resolve: ['require', 'reporter'],
    resolveInputs: (parsed) => {
        const inputs = [];
        for (const value of parsed._) {
            if (commands.has(value) || /^\w+=/.test(value))
                continue;
            inputs.push(toEntry(value));
        }
        return inputs;
    },
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    resolveConfig,
    args,
};
export default plugin;
