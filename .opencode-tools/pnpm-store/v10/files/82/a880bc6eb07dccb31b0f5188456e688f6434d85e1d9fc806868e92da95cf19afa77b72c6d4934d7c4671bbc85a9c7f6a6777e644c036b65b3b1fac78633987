import { toModule, toEntry } from '../../util/input.js';
import { join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { createCompiler } from './compiler.js';
import { getTaglibDependencies } from './taglibs.js';
const title = 'Marko';
const enablers = ['marko'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['**/marko.json', '**/marko-tag.json'];
const tagDiscoveryDirs = ['components', 'tags'];
const scriptExtensions = '{js,jsx,ts,tsx,mjs,cjs,mts,cts}';
const styleExtensions = '{css,less,scss,sass,styl,stylus}';
const tagFilePatterns = [
    '**/*.marko',
    `**/{component,component-browser}.${scriptExtensions}`,
    `**/*.{component,component-browser}.${scriptExtensions}`,
    `**/style.${styleExtensions}`,
    `**/*.style.${styleExtensions}`,
];
const tagProduction = tagFilePatterns.map(pattern => `**/{${tagDiscoveryDirs.join(',')}}/${pattern}`);
const production = tagProduction;
const tagDefFields = [
    'template',
    'renderer',
    'parse',
    'migrate',
    'transform',
    'analyze',
    'translate',
];
const resolveConfig = (localConfig, options) => {
    const { configFileName, configFileDir } = options;
    const inputs = production.map(pattern => toEntry(pattern, { production: true }));
    if (!localConfig)
        return inputs;
    if (configFileName === 'marko.json') {
        return tagProduction.map(pattern => toEntry(join(configFileDir, pattern), { production: true }));
    }
    for (const field of tagDefFields) {
        for (const id of [localConfig[field]].flat()) {
            if (typeof id === 'string')
                inputs.push(toModule(id));
        }
    }
    return inputs;
};
const registerCompilers = async ({ cwd, dependencies, registerCompiler, hasDependency }) => {
    if (hasDependency('marko')) {
        const { tagDependencies, fallbackDependencies } = await getTaglibDependencies(cwd, dependencies);
        registerCompiler({ extension: '.marko', compiler: createCompiler(tagDependencies, fallbackDependencies) });
    }
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    production,
    resolveConfig,
    registerCompilers,
};
export default plugin;
