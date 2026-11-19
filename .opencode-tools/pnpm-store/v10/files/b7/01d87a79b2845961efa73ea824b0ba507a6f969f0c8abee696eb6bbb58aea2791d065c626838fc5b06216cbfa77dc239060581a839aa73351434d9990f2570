import { arrayify } from '../../util/array.js';
import { get } from '../../util/object.js';
import { hasDependency } from '../../util/plugin.js';
import { scanVarlockFiles } from './scan.js';
const title = 'Varlock';
const enablers = ['varlock'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const getLoadPaths = (manifest) => arrayify(get(manifest, 'varlock.loadPath'));
const resolve = options => {
    const loadPaths = getLoadPaths(options.manifest);
    return scanVarlockFiles(loadPaths.length > 0 ? loadPaths : ['.'], options.cwd);
};
const args = {
    alias: { path: ['p'] },
    string: ['path', 'env'],
    fromArgs: parsed => (parsed._[0] === 'run' ? (parsed['--'] ?? []) : []),
    resolveInputs: (parsed, { cwd, manifest }) => {
        const paths = arrayify(parsed.path);
        const loadPaths = getLoadPaths(manifest);
        const environment = arrayify(parsed.env).at(-1);
        return scanVarlockFiles(paths.length > 0 ? paths : environment ? (loadPaths.length > 0 ? loadPaths : ['.']) : [], cwd);
    },
};
const plugin = {
    title,
    enablers,
    isEnabled,
    args,
    resolve,
};
export default plugin;
