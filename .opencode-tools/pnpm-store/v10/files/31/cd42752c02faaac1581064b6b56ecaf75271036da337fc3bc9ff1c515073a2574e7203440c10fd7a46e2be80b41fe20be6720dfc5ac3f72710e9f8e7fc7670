import { toConfig, toEntry, toDependency } from '../../util/input.js';
import { toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
import { clientToPackages } from './helpers.js';
import { createKnexClientVisitor } from './visitors/clientCall.js';
const title = 'Knex';
const enablers = ['knex'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['knexfile.{js,cjs,mjs,ts,cts,mts}'];
const processKnexConfig = (config, dir) => {
    const inputs = [];
    if (config.client) {
        const packages = clientToPackages(config.client);
        inputs.push(...packages.map(pkg => toDependency(pkg, { production: true, optional: true })));
    }
    if (config.migrations?.directory) {
        const dirs = Array.isArray(config.migrations.directory)
            ? config.migrations.directory
            : [config.migrations.directory];
        inputs.push(...dirs.map(directory => toEntry(`${directory}/*.{js,ts}`, { dir })));
    }
    if (config.seeds?.directory) {
        const dirs = Array.isArray(config.seeds.directory) ? config.seeds.directory : [config.seeds.directory];
        inputs.push(...dirs.map(directory => toEntry(`${directory}/*.{js,ts}`, { dir })));
    }
    return inputs;
};
const resolveConfig = (config, { configFileDir }) => {
    const configs = 'client' in config && config.client ? [config] : Object.values(config);
    return configs.flatMap(cfg => (typeof cfg === 'object' && cfg !== null ? processKnexConfig(cfg, configFileDir) : []));
};
const registerVisitors = ({ ctx, registerVisitor }) => {
    registerVisitor(createKnexClientVisitor(ctx));
};
const args = {
    string: ['cwd', 'knexfile'],
    resolveInputs: (parsed, { cwd }) => parsed.knexfile ? [toConfig('knex', parsed.knexfile, { dir: parsed.cwd ? toAbsolute(parsed.cwd, cwd) : cwd })] : [],
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    registerVisitors,
    args,
};
export default plugin;
