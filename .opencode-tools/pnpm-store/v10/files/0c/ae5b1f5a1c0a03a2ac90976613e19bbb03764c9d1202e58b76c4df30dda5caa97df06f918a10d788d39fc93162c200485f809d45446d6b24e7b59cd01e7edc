import { toEntry } from '../../util/input.js';
import { join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Mock Service Worker';
const enablers = ['msw'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['package.json'];
const entry = ['mockServiceWorker.js'];
const resolveConfig = async (localConfig) => {
    const dirs = localConfig?.workerDirectory ? [localConfig.workerDirectory].flat() : ['.'];
    const inputs = [];
    for (const dir of dirs)
        for (const pattern of entry)
            inputs.push(toEntry(join(dir, pattern)));
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    resolveConfig,
};
export default plugin;
