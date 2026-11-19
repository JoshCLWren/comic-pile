import { toModule, toEntryPath, toDependency } from '../../util/input.js';
import { isInternal } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'MDX';
const enablers = ['astro', 'mdxlint'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['tsconfig.json'];
const takeDependencies = (plugins) => {
    const inputs = [];
    if (Array.isArray(plugins)) {
        for (const plugin of plugins) {
            if (typeof plugin === 'string')
                inputs.push(toDependency(plugin));
            else if (Array.isArray(plugin) && typeof plugin[0] === 'string')
                inputs.push(toDependency(plugin[0]));
        }
    }
    return inputs;
};
export const contentMappers = ['mdx-content-mapper', '@mdx-js/content-mapper'];
const bundledPlugins = ['remark-mdx-frontmatter'];
export const toProviderInput = (provider, dir) => isInternal(provider) || provider.startsWith('#')
    ? toEntryPath(provider, { production: true })
    : toModule(provider, { dir, production: true });
export const resolveContentMapperOptions = (options, dir) => {
    const inputs = takeDependencies(options.remarkPlugins).filter(input => !bundledPlugins.includes(input.specifier));
    const provider = options.providerImportSource;
    if (typeof provider === 'string')
        inputs.push(toProviderInput(provider, dir));
    return inputs;
};
const resolveConfig = async (config, options) => {
    const { configFileName } = options;
    if (configFileName === 'tsconfig.json' && 'mdx' in config)
        return takeDependencies(config.mdx.plugins);
    return [];
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
};
export default plugin;
