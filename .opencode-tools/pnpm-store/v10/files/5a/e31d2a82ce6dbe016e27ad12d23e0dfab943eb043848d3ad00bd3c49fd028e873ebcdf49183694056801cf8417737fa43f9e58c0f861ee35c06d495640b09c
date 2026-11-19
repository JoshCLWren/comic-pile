import { arrayify } from '../../util/array.js';
import { findFileWithExtensions } from '../../util/fs.js';
import { _dirGlob, _glob, negate } from '../../util/glob.js';
import { toAlias, toConfig, toModule, toEntryPath, toDependency, toEntry } from '../../util/input.js';
import { dirname, join, toAbsolute } from '../../util/path.js';
import { hasDependency, load } from '../../util/plugin.js';
import { createRstestMockVisitor } from './visitors/mock.js';
const title = 'Rstest';
const enablers = ['@rstest/core'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const configExtensions = ['.mts', '.mjs', '.ts', '.js', '.cjs', '.cts'];
const config = ['rstest.config.{js,cjs,mjs,ts,cts,mts}'];
const mocks = ['**/__mocks__/**/*.?(c|m)[jt]s?(x)'];
const testEntry = ['**/*.{test,spec}.?(c|m)[jt]s?(x)'];
const entry = [...testEntry, ...mocks];
const getEnvironmentDependency = (name) => (name && name !== 'node' ? [toDependency(name)] : []);
const replaceRootDir = (path, root) => path.replace('<rootDir>', root);
const configParams = { env: 'test', command: 'run', envMode: 'test' };
const getConfig = async (config) => typeof config === 'function' ? await config(configParams) : config;
const resolveConfig = async (localConfig, options) => {
    const { cwd, configFileDir, configFilePath, getManifest, isResolvedConfigFile } = options;
    const cfg = await getConfig(localConfig);
    const runnerRoot = toAbsolute(cfg.root ?? '.', isResolvedConfigFile ? configFileDir : cwd);
    const manifest = getManifest(cwd);
    const seen = new Set([configFilePath]);
    const inputs = [];
    const addProject = async (project, projectRoot) => {
        const toPattern = (pattern) => toAbsolute(replaceRootDir(pattern, projectRoot), projectRoot);
        if (!options.config.entry) {
            const include = [];
            const exclude = [...(Array.isArray(project.exclude) ? project.exclude : (project.exclude?.patterns ?? []))];
            for (const pattern of [...(project.include ?? testEntry), ...mocks]) {
                if (pattern.startsWith('!'))
                    exclude.push(pattern.slice(1));
                else
                    include.push(toPattern(pattern));
            }
            const entries = exclude.length === 0
                ? include
                : await _glob({ cwd, patterns: [...include, ...exclude.map(pattern => negate(toPattern(pattern)))] });
            for (const entry of entries)
                inputs.push(exclude.length === 0 ? toEntry(entry) : toEntryPath(entry));
        }
        const env = project.testEnvironment;
        inputs.push(...getEnvironmentDependency(typeof env === 'string' ? env : env?.name));
        for (const specifier of [project.setupFiles ?? [], project.globalSetup ?? []].flat()) {
            inputs.push(toModule(replaceRootDir(specifier, projectRoot), { dir: projectRoot }));
        }
        if (project.browser?.enabled) {
            inputs.push(toDependency('@rstest/browser'), toDependency('playwright'));
        }
        for (const [name, value] of Object.entries(project.resolve?.alias ?? {})) {
            const prefixes = [];
            for (const target of arrayify(value))
                prefixes.push(target.startsWith('.') ? join(runnerRoot, target) : target);
            if (name.endsWith('$')) {
                inputs.push(toAlias(name.slice(0, -1), prefixes));
            }
            else {
                inputs.push(toAlias(name, prefixes), toAlias(`${name}/*`, prefixes.map(prefix => `${prefix}/*`)));
            }
        }
    };
    const addProjects = async (projects, projectsRoot) => {
        const patterns = [];
        for (const project of projects) {
            if (typeof project === 'string')
                patterns.push(replaceRootDir(project, projectsRoot));
            else
                await addProject(project, toAbsolute(replaceRootDir(project.root ?? projectsRoot, projectsRoot), runnerRoot));
        }
        const [files, dirs] = await Promise.all([
            _glob({ cwd: projectsRoot, patterns, gitignore: false }),
            _dirGlob({ cwd: projectsRoot, patterns, gitignore: false }),
        ]);
        for (const dir of dirs) {
            const projectRoot = toAbsolute(dir, projectsRoot);
            const filePath = findFileWithExtensions(join(projectRoot, 'rstest.config'), configExtensions);
            if (filePath)
                files.push(filePath);
            else
                await addProject({}, projectRoot);
        }
        for (const filePath of files) {
            if (seen.has(filePath))
                continue;
            seen.add(filePath);
            const project = getManifest(dirname(filePath)) === manifest
                ? await load(filePath)
                    .then(getConfig)
                    .catch(() => undefined)
                : undefined;
            if (!project) {
                inputs.push(toConfig('rstest', filePath));
                continue;
            }
            inputs.push(toEntryPath(filePath));
            if (project.projects)
                await addProjects(project.projects, dirname(filePath));
            else
                await addProject(project, toAbsolute(project.root ?? dirname(filePath), runnerRoot));
        }
    };
    if (cfg.projects)
        await addProjects(cfg.projects, runnerRoot);
    else
        await addProject(cfg, runnerRoot);
    if (!isResolvedConfigFile) {
        inputs.push(toDependency(`@rstest/coverage-${cfg.coverage?.provider ?? 'istanbul'}`, { optional: true }));
    }
    return inputs;
};
const args = {
    config: true,
    resolveInputs: parsed => getEnvironmentDependency(parsed.testEnvironment),
};
const registerVisitors = ({ ctx, registerVisitor }) => {
    registerVisitor(createRstestMockVisitor(ctx));
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    resolveConfig,
    args,
    registerVisitors,
};
export default plugin;
