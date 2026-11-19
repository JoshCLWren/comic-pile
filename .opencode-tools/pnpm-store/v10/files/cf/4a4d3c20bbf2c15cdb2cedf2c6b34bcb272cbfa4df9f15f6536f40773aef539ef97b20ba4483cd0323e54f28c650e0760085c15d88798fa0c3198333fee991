import { hasDependency } from '../../util/plugin.js';
import { config } from '../vite/index.js';
import { production, resolveFromAST } from './resolveFromAST.js';
const title = '@solidjs/vite-plugin';
const enablers = ['@solidjs/vite-plugin'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const note = `Without a Vite config, the default entry patterns are used. With a config, start entries are only added when \`start\` is enabled. Paths like \`start.app\` replace the matching default, and the \`ssr\` option decides which files Solid loads. \`serverFunctions.configure\` is added with or without \`start\`.`;
export const docs = { note };
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    production,
    resolveFromAST,
};
export default plugin;
