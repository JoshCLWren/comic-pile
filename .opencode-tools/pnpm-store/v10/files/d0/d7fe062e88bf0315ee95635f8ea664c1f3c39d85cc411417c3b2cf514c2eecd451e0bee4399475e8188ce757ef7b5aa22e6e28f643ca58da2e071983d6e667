import parseArgs, { helpText } from './util/cli-arguments.js';
import { version } from './version.js';
let args = {};
try {
    args = parseArgs();
}
catch (error) {
    if (error instanceof Error) {
        console.error(error.message);
        console.log(`\n${helpText}`);
        process.exit(1);
    }
    throw error;
}
if (args.help) {
    console.log(helpText);
    process.exit(0);
}
if (args.version) {
    console.log(version);
    process.exit(0);
}
const { runCLI } = await import('./run-cli.js');
await runCLI(args);
