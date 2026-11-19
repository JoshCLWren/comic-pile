import { collectPropertyValues } from '../../typescript/ast-helpers.js';
import { toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'tsup';
const enablers = ['tsup'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['tsup.config.{js,ts,cjs,mjs,cts,mts,json}', 'package.json'];
const isLoadConfig = ({ configFileName }) => configFileName === 'package.json' || configFileName.endsWith('.json');
const resolveConfig = async (config) => {
    if (typeof config === 'function')
        config = await config({});
    const entryPatterns = [config]
        .flat()
        .flatMap(config => {
        if (!config.entry)
            return [];
        if (Array.isArray(config.entry))
            return config.entry;
        return Object.values(config.entry);
    })
        .map(id => toEntry(id, { production: true, allowIncludeExports: true }));
    return entryPatterns;
};
const resolveFromAST = program => Array.from(collectPropertyValues(program, 'entry'), id => toEntry(id, { production: true, allowIncludeExports: true }));
const args = {
    config: true,
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    isLoadConfig,
    resolveConfig,
    resolveFromAST,
    args,
};
export default plugin;
