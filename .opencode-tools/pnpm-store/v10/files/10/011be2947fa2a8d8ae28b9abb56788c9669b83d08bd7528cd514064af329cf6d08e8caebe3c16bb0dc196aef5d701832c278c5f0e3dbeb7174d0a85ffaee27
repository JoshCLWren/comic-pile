import parseArgs from '../../util/parse-args.js';
import { parse } from 'unbash';
import { getCommandWords, collectCommands } from '../../util/scripts.js';
const BIN = 'svelte-package';
export const DEFAULT_INPUT = 'src/lib';
export const DEFAULT_OUTPUT = 'dist';
const parseCommandIO = (args) => {
    const parsed = parseArgs(args, { string: ['i', 'o', 'input', 'output'], alias: { input: ['i'], output: ['o'] } });
    return { input: parsed.input ?? DEFAULT_INPUT, output: parsed.output ?? DEFAULT_OUTPUT };
};
export const parseScripts = (scripts) => {
    const out = [];
    for (const script of Object.values(scripts ?? {})) {
        if (typeof script !== 'string' || !script.includes(BIN))
            continue;
        try {
            const parsed = parse(script);
            for (const statement of parsed.commands) {
                for (const node of collectCommands(statement.command)) {
                    if (node.name?.value === BIN)
                        out.push(parseCommandIO(getCommandWords(node).map(word => word.value)));
                }
            }
        }
        catch { }
    }
    return out;
};
