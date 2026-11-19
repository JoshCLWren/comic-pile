import { findImportedCalls, findProperty } from '../../typescript/ast-helpers.js';
import { getStringValue } from '../../typescript/ast-nodes.js';
import { isFile } from '../../util/fs.js';
import { toEntryPath, toEntry } from '../../util/input.js';
import { join, toAbsolute } from '../../util/path.js';
import { getViteRoot } from '../vite/helpers.js';
const entryExtensions = ['tsx', 'jsx', 'ts', 'js', 'mjs', 'tsrx'];
const entryStems = {
    entryServer: 'src/entry-server',
    entryClient: 'src/entry-client',
};
const conventions = {
    entryServer: `src/entry-server.{${entryExtensions.join(',')}}`,
    entryClient: `src/entry-client.{${entryExtensions.join(',')}}`,
    app: 'src/{App,app}.{tsx,jsx,ts,js,tsrx}',
    document: 'src/Document.{tsx,jsx,tsrx}',
    env: 'env.{ts,js}',
};
export const production = Object.values(conventions);
const startOptions = ['app', 'document', 'entryServer', 'entryClient', 'middleware', 'instrument', 'setup', 'env'];
const isBoolean = (node, value) => node?.type === 'Literal' && node.value === value;
const hasEntryFile = (root, stem) => {
    for (const extension of entryExtensions)
        if (isFile(root, `${stem}.${extension}`))
            return true;
    return false;
};
export const resolveFromAST = (program, options) => {
    const root = getViteRoot(program, options.cwd);
    const patterns = new Set();
    const paths = new Set();
    for (const call of findImportedCalls(program, '@solidjs/vite-plugin')) {
        const arg = call.arguments[0];
        if (arg?.type !== 'ObjectExpression')
            continue;
        const configure = getStringValue(findProperty(findProperty(arg, 'serverFunctions'), 'configure'));
        if (configure)
            paths.add(configure);
        const start = findProperty(arg, 'start');
        if (!start || isBoolean(start, false))
            continue;
        const values = {};
        for (const name of startOptions) {
            values[name] = start.type === 'ObjectExpression' ? findProperty(start, name) : undefined;
        }
        const isAuthored = (name) => Boolean(getStringValue(values[name])) || hasEntryFile(root, entryStems[name]);
        const ssr = findProperty(arg, 'ssr');
        const skip = new Set();
        if (!ssr || isBoolean(ssr, false)) {
            skip.add('entryServer');
            skip.add('setup');
            if (isAuthored('entryClient'))
                skip.add('app');
        }
        else if (isBoolean(ssr, true) && isAuthored('entryServer') && isAuthored('entryClient')) {
            skip.add('app');
            skip.add('document');
        }
        for (const name of startOptions) {
            if (skip.has(name))
                continue;
            const value = values[name];
            const path = getStringValue(value);
            if (path)
                paths.add(path);
            else if (name in conventions && !(name === 'env' && isBoolean(value, false)))
                patterns.add(conventions[name]);
        }
    }
    const inputs = [];
    for (const pattern of patterns)
        inputs.push(toEntry(join(root, pattern), { production: true }));
    for (const id of paths)
        inputs.push(toEntryPath(toAbsolute(id, root), { production: true }));
    return inputs;
};
