import { spawningArgs } from '../../binaries/util.js';
const title = 'env-cmd';
const args = {
    boolean: true,
    string: ['environments', 'file', 'rc-file'],
    alias: { environments: ['e'], file: ['f'], 'rc-file': ['r'] },
    fromArgs: (parsed, argv) => {
        const command = spawningArgs(parsed, argv);
        return parsed['use-shell'] ? command.join(' ') : command;
    },
};
const plugin = {
    title,
    args,
};
export default plugin;
