import { compact } from '../../util/array.js';
import { toModule, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'SWC';
const enablers = ['@swc/core'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['.swcrc'];
const resolveConfig = async (config, options) => {
    const plugins = [];
    const inputs = [];
    for (const item of [config].flat()) {
        for (const [id] of item?.jsc?.experimental?.plugins ?? [])
            plugins.push(id);
        if (item?.jsc?.externalHelpers)
            inputs.push(toDependency('@swc/helpers', { production: true }));
    }
    for (const id of compact(plugins))
        inputs.push(isInternal(id) ? toModule(id, { dir: options.cwd }) : toDependency(id));
    return inputs;
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
