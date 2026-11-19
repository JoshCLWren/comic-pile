import { toConfig, toEntry } from '../../util/input.js';
import { join, toAbsolute } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'MikroORM';
const enablers = [/^@mikro-orm\//];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = [
    'src/mikro-orm.config.{ts,js}',
    'mikro-orm.config.{ts,js}',
    'dist/mikro-orm.config.js',
    'build/mikro-orm.config.js',
    'package.json',
];
const DEFAULT_MIGRATIONS_GLOB = '!(*.d).{js,ts,cjs}';
const DEFAULT_SEEDER_GLOB = '!(*.d).{js,ts}';
const ENTITY_EXTENSIONS = 'js,cjs,mjs,ts,cts,mts';
const toStrings = (value) => (Array.isArray(value) ? value : [value]).filter((item) => typeof item === 'string');
const isRecord = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const isMikroOrmOptions = (value) => isRecord(value);
const isMikroOrmPackageJson = (value) => isRecord(value) &&
    'configPaths' in value &&
    (typeof value.configPaths === 'string' || Array.isArray(value.configPaths));
const isMikroOrmConfigFactory = (value) => typeof value === 'function';
const isMikroOrmConfigItem = (value) => isMikroOrmOptions(value) || isMikroOrmConfigFactory(value);
const entitySpecialRegex = /[*?{}[]/u;
const entityFileExtensionRegex = /\.(?:[cm]?[jt]s)$/u;
const toEntityEntry = (specifier, extensions, baseDir) => {
    const hasPattern = entitySpecialRegex.test(specifier);
    const hasExtension = entityFileExtensionRegex.test(specifier);
    const pattern = hasPattern || hasExtension ? specifier : join(specifier, `**/*.{${extensions}}`);
    return toEntry(toAbsolute(pattern, baseDir), { production: true });
};
const toFolderEntries = (paths, glob, baseDir) => paths.map(path => toEntry(toAbsolute(join(path, glob), baseDir), { production: true }));
const resolveConfig = async (config, options) => {
    if (options.configFileName === 'package.json') {
        if (!isMikroOrmPackageJson(config))
            return [];
        const configPaths = toStrings(config.configPaths);
        return configPaths.map(path => toConfig('mikro-orm', path, { dir: options.cwd }));
    }
    const configItems = (Array.isArray(config) ? config : [config]).filter(isMikroOrmConfigItem);
    const resolvedConfigs = await Promise.all(configItems.map(async (configItem) => isMikroOrmConfigFactory(configItem) ? await configItem('default') : configItem));
    const configs = resolvedConfigs
        .flatMap(config => (Array.isArray(config) ? config : [config]))
        .filter(isMikroOrmOptions);
    return configs.flatMap(config => {
        const baseDir = typeof config.baseDir === 'string' ? toAbsolute(config.baseDir, options.cwd) : options.cwd;
        const inputs = [];
        const entities = [...toStrings(config.entities), ...toStrings(config.entitiesTs)];
        inputs.push(...entities.map(path => toEntityEntry(path, ENTITY_EXTENSIONS, baseDir)));
        if (config.migrations?.migrationsList === undefined) {
            const migrationsTs = toStrings(config.migrations?.pathTs);
            const migrations = migrationsTs.length > 0 ? migrationsTs : toStrings(config.migrations?.path);
            const paths = migrations.length > 0 ? migrations : ['./migrations'];
            inputs.push(...toFolderEntries(paths, config.migrations?.glob ?? DEFAULT_MIGRATIONS_GLOB, baseDir));
        }
        const seedersTs = toStrings(config.seeder?.pathTs);
        const seeders = seedersTs.length > 0 ? seedersTs : toStrings(config.seeder?.path);
        const seederPaths = seeders.length > 0 ? seeders : ['./seeders'];
        inputs.push(...toFolderEntries(seederPaths, config.seeder?.glob ?? DEFAULT_SEEDER_GLOB, baseDir));
        return inputs;
    });
};
const args = {
    binaries: ['mikro-orm'],
    config: true,
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    args,
    resolveConfig,
};
export default plugin;
