import { forEachChild, parse } from 'unbash';
import { debugLogObject } from '../util/debug.js';
import { extractBinary } from '../util/modules.js';
import { relative } from '../util/path.js';
import { truncate } from '../util/string.js';
import { isScriptExpansion } from '../util/scripts.js';
import { getDependenciesFromCommand } from './command.js';
import { toForwardedScript } from './plugins.js';
export const getDependenciesFromScript = (script, options) => {
    if (!script)
        return [];
    const fromArgs = (args, opts) => {
        if (args.length === 0)
            return [];
        return getDependenciesFromScript(toForwardedScript(args), {
            ...options,
            isForwardedArgs: false,
            ...opts,
        });
    };
    const fromWords = (args, opts) => getDependenciesFromScript(toForwardedScript(args), opts);
    const definedFunctions = new Set();
    const collectFunctionNames = (statements) => {
        for (const stmt of statements)
            if (stmt.command.type === 'Function')
                definedFunctions.add(stmt.command.name.text);
    };
    const processScript = (s) => {
        collectFunctionNames(s.commands);
        const inputs = [];
        const visit = (node) => {
            if (node.type === 'Command')
                inputs.push(...processCommand(node));
            if (isScriptExpansion(node)) {
                if (node.script)
                    inputs.push(...processScript(node.script));
            }
            else
                forEachChild(node, visit);
        };
        visit(s);
        return inputs;
    };
    const processCommand = (node) => {
        if (definedFunctions.size && node.name && definedFunctions.has(extractBinary(node.name.value)))
            return [];
        return getDependenciesFromCommand(node, { ...options, fromArgs }, fromWords);
    };
    try {
        const parsed = parse(script);
        if (!parsed.commands)
            return [];
        return processScript(parsed);
    }
    catch (error) {
        const msg = `Warning: failed to parse and ignoring script in ${relative(options.cwd, options.containingFilePath)} (${truncate(script, 30)})`;
        debugLogObject('*', msg, error);
        return [];
    }
};
