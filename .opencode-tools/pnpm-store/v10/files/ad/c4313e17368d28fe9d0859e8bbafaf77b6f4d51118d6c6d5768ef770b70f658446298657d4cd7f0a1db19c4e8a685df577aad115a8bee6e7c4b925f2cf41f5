import { run } from '../run.js';
import { createOptions } from '../util/create-options.js';
import { createPreprocessor, toReporterOptions } from '../util/preprocessor.js';
import { clearResolverCache } from '../util/resolve.js';
import { clearModuleResolutionCaches } from '../typescript/resolve-module-names.js';
import { clearGlobCache } from '../util/glob-cache.js';
import { clearGitignoreCache } from '../util/gitignore-cache.js';
import { unload } from '../util/loader.js';
import { buildFileDescriptor } from './file-descriptor.js';
import { buildPackageJsonDescriptor } from './package-json-descriptor.js';
import { SessionConfigurationChangedError } from './configuration.js';
export const createSession = async (options) => {
    const initialize = async (options) => {
        const { session, results } = await run(options);
        if (!session)
            throw new Error('Unable to initialize watch session');
        const preprocess = options.preprocessor.length > 0 ? await createPreprocessor(options.preprocessor) : undefined;
        const updateResults = async () => {
            const collected = session.getIssues();
            const data = preprocess
                ? await preprocess({ ...toReporterOptions(options, results), ...structuredClone(collected) })
                : collected;
            results.issues = data.issues;
            results.counters = data.counters;
            results.tagHints = data.tagHints;
            results.configurationHints = data.configurationHints;
            results.hasConfigLoadErrors = collected.hasConfigLoadErrors;
        };
        await updateResults();
        return { session, results, options, updateResults, preprocess };
    };
    let current = await initialize(options);
    const results = current.results;
    let pending = Promise.resolve();
    const processChanges = async (changes) => {
        try {
            const update = await current.session.handleFileChanges(changes);
            if (update) {
                await current.updateResults();
                Object.assign(results, current.results);
            }
            return update;
        }
        catch (error) {
            if (!(error instanceof SessionConfigurationChangedError))
                throw error;
            const startTime = performance.now();
            clearResolverCache();
            clearModuleResolutionCaches();
            clearGlobCache();
            clearGitignoreCache();
            const { configurationFiles } = current.session;
            if (configurationFiles)
                unload(configurationFiles.getAffected(changes, current.options.cwd));
            const nextOptions = await createOptions(current.options.createdFrom, true);
            current = await initialize({ ...nextOptions, isCache: false });
            Object.assign(results, current.results);
            return { duration: performance.now() - startTime, mem: process.memoryUsage().heapUsed };
        }
    };
    return {
        handleFileChanges: changes => {
            const update = pending.then(() => processChanges(changes));
            pending = update.then(() => { }, () => { });
            return update;
        },
        getIssues: () => (current.preprocess ? results : current.session.getIssues()),
        getResults: () => results,
        describeFile: (filePath, opts) => buildFileDescriptor(filePath, current.options.cwd, current.session.getGraph(), current.session.getEntryPaths(), opts),
        describePackageJson: () => buildPackageJsonDescriptor(current.session.getGraph(), current.session.getEntryPaths()),
    };
};
