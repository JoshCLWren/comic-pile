import { spawningArgs } from '../../binaries/util.js';
const title = 'c8';
const commands = new Set(['check-coverage', 'report']);
const args = {
    boolean: [
        '100',
        'all',
        'allowExternal',
        'check-coverage',
        'clean',
        'exclude-after-remap',
        'exclude-node-modules',
        'experimental-monocart',
        'merge-async',
        'omit-relative',
        'per-file',
        'skip-full',
    ],
    fromArgs: (parsed, args) => (commands.has(parsed._[0]) ? [] : spawningArgs(parsed, args)),
};
const plugin = {
    title,
    args,
};
export default plugin;
