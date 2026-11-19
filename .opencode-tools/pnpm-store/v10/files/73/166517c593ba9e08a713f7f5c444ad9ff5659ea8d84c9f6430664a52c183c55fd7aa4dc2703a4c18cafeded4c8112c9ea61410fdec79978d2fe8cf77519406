import { collectPropertyValues } from '../../typescript/ast-helpers.js';
import { toModule, toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Evalite';
const enablers = ['evalite'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['evalite.config.{ts,mts,js,mjs}'];
const entry = ['**/*.eval.?(m)ts'];
const resolveFromAST = (program, options) => {
    const inputs = [];
    if (!options.config.entry)
        for (const id of entry)
            inputs.push(toEntry(id));
    for (const id of collectPropertyValues(program, 'setupFiles'))
        inputs.push(toModule(id));
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    resolveFromAST,
};
export default plugin;
