import { toModule, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'mdxlint';
const enablers = ['mdxlint'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['.mdxlintrc', '.mdxlintrc.{json,js,cjs,mjs,yml,yaml}', 'package.json'];
const isPrefixed = (name) => name.startsWith('remark-') || name.startsWith('mdxlint-');
const toPluginName = (plugin) => {
    const slash = plugin.startsWith('@') ? plugin.indexOf('/') + 1 : 0;
    const name = plugin.slice(slash);
    return isPrefixed(name) ? plugin : `${plugin.slice(0, slash)}remark-${name}`;
};
const resolveConfig = config => {
    const inputs = [];
    for (const plugin of config.plugins ?? []) {
        const id = typeof plugin === 'string' ? plugin : Array.isArray(plugin) ? plugin[0] : undefined;
        if (typeof id !== 'string')
            continue;
        if (isInternal(id))
            inputs.push(toModule(id));
        else
            inputs.push(toDependency(toPluginName(id)));
    }
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
