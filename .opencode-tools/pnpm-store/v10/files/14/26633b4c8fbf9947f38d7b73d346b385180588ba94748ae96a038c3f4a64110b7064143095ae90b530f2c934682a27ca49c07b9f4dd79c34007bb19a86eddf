import { collectPropertyValues } from '../../typescript/ast-helpers.js';
import { toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Rollup';
const enablers = ['rollup'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['rollup.config.{js,cjs,mjs,ts}'];
const args = {
    alias: { plugin: ['p'] },
    config: ['config'],
    args: (args) => args.map(arg => (arg.startsWith('--watch.onEnd') ? `--_exec${arg.slice(13)}` : arg)),
    fromArgs: ['_exec'],
    resolve: ['plugin', 'configPlugin'],
};
const resolveFromAST = program => Array.from(collectPropertyValues(program, 'input'), id => toEntry(id, { production: true }));
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    args,
    resolveFromAST,
};
export default plugin;
