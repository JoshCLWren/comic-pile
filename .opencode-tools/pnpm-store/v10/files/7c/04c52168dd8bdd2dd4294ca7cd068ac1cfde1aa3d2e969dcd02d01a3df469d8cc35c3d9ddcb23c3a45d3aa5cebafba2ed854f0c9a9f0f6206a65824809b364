import { watch } from 'node:fs';
import { ConsoleStreamer } from '../ConsoleStreamer.js';
import watchReporter from '../reporters/watch.js';
import { debugLog } from '../util/debug.js';
import { hasErrorCause } from '../util/errors.js';
import { isFile } from '../util/fs.js';
import { logError } from '../util/log.js';
import { toPosix } from '../util/path.js';
import { hasUnhandledRejection } from '../util/unhandled-rejection.js';
import { createSession } from './session.js';
export const watchSession = async (options) => {
    const streamer = new ConsoleStreamer(options);
    const session = await createSession(options);
    const report = (duration) => {
        const { issues, counters } = session.getIssues();
        watchReporter(options, { issues, streamer, size: counters.processed - counters.files, duration });
    };
    const onError = (error) => {
        const message = error instanceof Error ? error.message : String(error);
        const reason = error instanceof Error && hasErrorCause(error) ? `\nReason: ${error.cause.message}` : '';
        logError(message + reason);
        process.exitCode = 2;
    };
    const watcher = watch(options.cwd, { recursive: true }, (eventType, filePath) => {
        debugLog('*', `(raw) ${eventType} ${filePath}`);
        if (typeof filePath !== 'string')
            return;
        const path = toPosix(filePath);
        const type = eventType === 'rename' ? (isFile(options.cwd, path) ? 'added' : 'deleted') : 'modified';
        session.handleFileChanges([{ type, filePath: path }]).then(update => {
            if (!update)
                return;
            process.exitCode = hasUnhandledRejection() ? 2 : 0;
            report(update.duration);
        }, onError);
    });
    watcher.on('error', error => {
        onError(error);
        watcher.close();
    });
    report();
};
