import { spawningArgs } from '../../binaries/util.js';
const title = 'dotenv';
const args = {
    binaries: ['dotenv', 'dotenv-cli'],
    args: (args) => (args[0] === 'run' ? args.slice(1) : args),
    boolean: ['debug', 'fast', 'override'],
    alias: { quiet: ['q'] },
    fromArgs: spawningArgs,
};
const plugin = {
    title,
    args,
};
export default plugin;
