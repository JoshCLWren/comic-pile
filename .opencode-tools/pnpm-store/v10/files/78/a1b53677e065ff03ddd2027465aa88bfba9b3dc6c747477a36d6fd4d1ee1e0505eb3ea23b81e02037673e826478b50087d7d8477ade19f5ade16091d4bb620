import { hasDependency } from '../../util/plugin.js';
const title = 'kysely-codegen';
const enablers = ['kysely-codegen'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const entry = [
    '.kysely-codegenrc.{js,ts,cjs}',
    '.config/kysely-codegenrc.{js,ts,cjs}',
    'kysely-codegen.config.{js,ts,cjs}',
];
const args = {
    config: ['config-file'],
};
const plugin = {
    title,
    enablers,
    isEnabled,
    entry,
    args,
};
export default plugin;
