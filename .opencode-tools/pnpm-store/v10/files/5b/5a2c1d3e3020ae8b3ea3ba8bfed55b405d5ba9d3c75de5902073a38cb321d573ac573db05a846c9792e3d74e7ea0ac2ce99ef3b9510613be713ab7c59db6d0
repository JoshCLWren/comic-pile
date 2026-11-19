import { fix } from './IssueFixer.js';
import { run } from './run.js';
import { createOptions } from './util/create-options.js';
import { getKnownErrors, hasErrorCause, isConfigurationError, isKnownError, isLoaderError, isModuleNotFoundError, } from './util/errors.js';
import { logError } from './util/log.js';
import { perfObserver } from './util/Performance.js';
import { createPreprocessor, toReporterOptions } from './util/preprocessor.js';
import { runReporters } from './util/reporter.js';
import { prettyMilliseconds } from './util/string.js';
import { hasUnhandledRejection, listenForUnhandledRejections } from './util/unhandled-rejection.js';
import { watchSession } from './session/watch.js';
export const runCLI = async (args) => {
    let cwd = process.cwd();
    listenForUnhandledRejections(() => cwd);
    if (perfObserver.isEnabled || perfObserver.isDurationEnabled)
        perfObserver.startRun();
    try {
        const options = await createOptions({ args });
        cwd = options.cwd;
        if (options.isWatch) {
            await watchSession(options);
            return;
        }
        const { results } = await run(options);
        if (options.isWatch || options.isTrace)
            return;
        const preprocess = await createPreprocessor(options.preprocessor);
        const finalData = await preprocess(toReporterOptions(options, results, args));
        if (options.isFix)
            await fix(finalData.issues, finalData.counters, options);
        await runReporters(args.reporter ?? ['symbols'], args['output-file'] ?? [], finalData);
        const totalErrorCount = Object.keys(finalData.report)
            .filter(reportGroup => finalData.report[reportGroup] && options.rules[reportGroup] === 'error')
            .reduce((errorCount, reportGroup) => errorCount + finalData.counters[reportGroup], 0);
        if (perfObserver.isEnabled || perfObserver.isDurationEnabled)
            perfObserver.finalize();
        if (perfObserver.isTimerifyFunctions)
            console.log(`\n${perfObserver.getTimerifiedFunctionsTable()}`);
        if (perfObserver.isMemoryUsageEnabled && !args['memory-realtime'])
            console.log(`\n${perfObserver.getMemoryUsageTable()}`);
        if (perfObserver.isEnabled || perfObserver.isDurationEnabled) {
            const duration = perfObserver.getCurrentDurationInMs();
            const startup = perfObserver.getProcessDurationInMs() - duration;
            console.log(`\nTotal running time: ${prettyMilliseconds(duration)} (+${prettyMilliseconds(startup)} startup)`);
            perfObserver.reset();
        }
        if (results.hasConfigLoadErrors || hasUnhandledRejection()) {
            process.exitCode = 2;
            return;
        }
        if (!args['no-exit-code'] &&
            (totalErrorCount > options.maxIssues ||
                (!options.isDisableConfigHints &&
                    options.isTreatConfigHintsAsErrors &&
                    finalData.configurationHints.length > 0) ||
                (!options.isDisableTagHints && options.isTreatTagHintsAsErrors && finalData.tagHints.size > 0))) {
            process.exitCode = 1;
            return;
        }
    }
    catch (error) {
        process.exitCode = 2;
        if (!args.debug && error instanceof Error && isKnownError(error)) {
            const knownErrors = getKnownErrors(error);
            for (const knownError of knownErrors)
                logError(knownError.message);
            if (hasErrorCause(knownErrors[0])) {
                console.error('Reason:', knownErrors[0].cause.message);
                if (isModuleNotFoundError(knownErrors[0].cause))
                    console.log('Module load error? Visit https://knip.dev/reference/known-issues');
                if (isLoaderError(knownErrors[0]))
                    console.log('Configuration file load error? Visit https://knip.dev/reference/known-issues');
            }
            if (isConfigurationError(knownErrors[0]))
                console.log('\nRun `knip --help` or visit https://knip.dev for help');
            process.exitCode = 2;
            return;
        }
        throw error;
    }
    process.exitCode = 0;
};
