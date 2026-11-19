import { escapePath } from 'tinyglobby';
import { findImportedCalls, findProperty } from '../../typescript/ast-helpers.js';
import { getStringValue } from '../../typescript/ast-nodes.js';
import { toEntry } from '../../util/input.js';
import { join, relative, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { getViteRoot } from '../vite/helpers.js';
const title = 'filesystem-routing';
const enablers = ['filesystem-routing'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['vite.config.{js,mjs,ts,cjs,mts,cts}'];
const defaultDir = 'src/routes';
const defaultExtensions = ['js', 'jsx', 'ts', 'tsx', 'tsrx'];
const production = [`${defaultDir}/**/*.{${defaultExtensions.join(',')}}`];
const resolveFromAST = (program, { config, cwd }) => {
    if (config.entry)
        return [];
    const root = getViteRoot(program, cwd);
    const toRouteEntry = (dir, pattern) => toEntry(join(cwd, escapePath(relative(cwd, dir)), pattern), { production: true });
    const calls = findImportedCalls(program, 'filesystem-routing/vite');
    if (calls.length === 0)
        return production.map(pattern => toRouteEntry(root, pattern));
    const inputs = [];
    for (const call of calls) {
        const options = call.arguments[0];
        const dir = getStringValue(findProperty(options, 'dir')) ?? defaultDir;
        const value = findProperty(options, 'extensions');
        const extensions = new Set();
        let useDefaults = value?.type !== 'ArrayExpression';
        if (value?.type === 'ArrayExpression') {
            for (const element of value.elements) {
                const extension = getStringValue(element);
                if (extension === undefined)
                    useDefaults = true;
                else
                    extensions.add(extension);
            }
        }
        if (useDefaults)
            for (const extension of defaultExtensions)
                extensions.add(extension);
        if (extensions.size === 0)
            continue;
        const suffix = extensions.size === 1 ? [...extensions][0] : `{${[...extensions].join(',')}}`;
        inputs.push(toRouteEntry(toAbsolute(dir, root), `**/*.${suffix}`));
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    production,
    resolveFromAST,
};
export default plugin;
