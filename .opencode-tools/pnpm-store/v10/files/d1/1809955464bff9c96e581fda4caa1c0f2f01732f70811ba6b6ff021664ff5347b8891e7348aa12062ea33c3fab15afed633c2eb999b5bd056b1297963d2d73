import { toEntryPath, toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Turborepo';
const enablers = ['turbo', '@turbo/gen'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const extensions = '{ts,js,cjs,mts,mjs}';
const entry = [`turbo/generators/config.${extensions}`];
const resolve = ({ cwd, rootCwd }) => (cwd === rootCwd ? [toEntry(`plopfile.${extensions}`)] : []);
const args = {
    string: ['config'],
    resolveInputs: (parsed, { cwd }) => (parsed._[0] === 'gen' || parsed._[0] === 'generate') && typeof parsed.config === 'string'
        ? [toEntryPath(parsed.config, { dir: cwd })]
        : [],
};
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
    resolve,
    args,
};
export default plugin;
