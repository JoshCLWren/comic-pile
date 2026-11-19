import { collectPropertyValues } from '../../typescript/ast-helpers.js';
import { toModule } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'ember-template-lint';
const enablers = ['ember-template-lint'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['.template-lintrc.{js,cjs,mjs}'];
const resolveFromAST = program => Array.from(collectPropertyValues(program, 'plugins'), id => toModule(id));
const args = {
    config: ['config-path'],
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveFromAST,
    args,
};
export default plugin;
