import { isFile } from '../../util/fs.js';
import { toDependency, toEntry } from '../../util/input.js';
const title = 'pnpm';
const enablers = 'This plugin is enabled when a `pnpm-lock.yaml` or `pnpm-workspace.yaml` file is found in the root directory, or when `pnpm@` is specified in the `packageManager` field of `package.json`.';
const isEnabled = async ({ cwd, manifest }) => manifest.packageManager?.startsWith('pnpm@') || isFile(cwd, 'pnpm-lock.yaml') || isFile(cwd, 'pnpm-workspace.yaml');
const isRootOnly = true;
const entry = ['.pnpmfile.{cjs,mjs}'];
const config = ['package.json', 'pnpm-workspace.yaml'];
const resolveConfig = config => {
    const inputs = entry.map(id => toEntry(id));
    const packageExtensions = config?.pnpm?.packageExtensions || config?.packageExtensions;
    if (packageExtensions) {
        for (const extension of Object.values(packageExtensions)) {
            if (extension.peerDependencies) {
                for (const dep of Object.keys(extension.peerDependencies))
                    inputs.push(toDependency(dep, { optional: true }));
            }
        }
    }
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    isRootOnly,
    entry,
    config,
    resolveConfig,
};
export default plugin;
