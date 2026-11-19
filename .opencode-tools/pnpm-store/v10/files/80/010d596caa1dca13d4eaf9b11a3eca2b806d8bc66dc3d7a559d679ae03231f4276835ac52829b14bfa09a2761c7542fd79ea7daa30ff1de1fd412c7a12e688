import { ResolvedCommand } from 'package-manager-detector';
import { FormatterCheckerOptions, FormatFilesResult, FormatterRunnerOptions, FormatlyReportChildProcessResult, FormatlyReportDryRunResult, FormatterTextRunnerOptions, FormatTextResult } from '../types.js';

/**
 * A command that lists which of the given files aren't formatted.
 */
interface FormatCheckCommand {
    args: (filePaths: string[]) => string[];
    command: string;
    /**
     * Exit code the command uses to report unformatted files, if not 1.
     */
    differencesCode?: number;
    /**
     * Parses the command's output into the paths of unformatted files.
     */
    parse: (output: SpawnedOutput) => string[];
    /**
     * Parses the command's output into failures other than unformatted files,
     * for commands that also exit with the differences code on errors.
     */
    parseFailures?: (output: SpawnedOutput) => string[];
}
/**
 * A {@link FormatCheckCommand} run through the project's package manager.
 */
interface FormatCheckPackageCommand extends FormatCheckCommand, PackageCommandSource {
}
/**
 * A command that formats text piped in through stdin and prints to stdout.
 * Formatters take the file's path through different flags, so args are
 * created from the path rather than listed statically.
 */
interface FormatTextCommand {
    args: (filePath: string) => string[];
    command: string;
}
/**
 * A {@link FormatTextCommand} run through the project's package manager.
 */
interface FormatTextPackageCommand extends FormatTextCommand, PackageCommandSource {
}
/**
 * A command run through the project's package manager.
 */
interface PackageCommand extends PackageCommandSource, ResolvedCommand {
}
interface PackageCommandSource {
    /**
     * The command's bin name.
     */
    command: string;
    /**
     * The npm package providing the bin, if it's named differently than the bin.
     */
    packageName?: string;
}
interface SpawnedOutput {
    code: null | number;
    error?: never;
    signal: NodeJS.Signals | null;
    stderr: string;
    stdout: string;
}
declare function createOutputError(command: string, { code, signal, stderr, }: Pick<SpawnedOutput, "code" | "signal"> & {
    stderr?: string;
}): Error;
declare function runFormatterCheckCommand({ args, ...check }: FormatCheckCommand, { cwd, filePaths }: FormatterCheckerOptions): Promise<FormatFilesResult>;
declare function runFormatterCommand({ args, command }: ResolvedCommand, { cwd, dryRun, patterns }: FormatterRunnerOptions): Promise<FormatlyReportChildProcessResult | FormatlyReportDryRunResult>;
declare function runFormatterTextCommand({ args, command }: FormatTextCommand, { cwd, filePath, text }: FormatterTextRunnerOptions): Promise<FormatTextResult>;
declare function runPackageFormatterCheckCommand({ args, command, packageName, ...check }: FormatCheckPackageCommand, { cwd, filePaths }: FormatterCheckerOptions): Promise<FormatFilesResult>;
declare function runPackageFormatterCommand({ args, ...source }: PackageCommand, { cwd, dryRun, patterns }: FormatterRunnerOptions): Promise<FormatlyReportChildProcessResult | FormatlyReportDryRunResult>;
declare function runPackageFormatterTextCommand({ args, ...source }: FormatTextPackageCommand, { cwd, filePath, text }: FormatterTextRunnerOptions): Promise<FormatTextResult>;
/**
 * Finds a bin installed in node_modules/.bin of cwd or any of its parents.
 * Spawning it directly skips the package manager's startup cost.
 * Windows is skipped because its bins are .cmd shims that need a shell.
 * @see https://github.com/JoshuaKGoldberg/formatly/issues/629
 */
declare function resolvePackageCommand({ command, packageName }: PackageCommandSource, args: string[], cwd: string): Promise<ResolvedCommand>;

export { type FormatCheckCommand, type FormatCheckPackageCommand, type FormatTextCommand, type FormatTextPackageCommand, type PackageCommand, type SpawnedOutput, createOutputError, resolvePackageCommand, runFormatterCheckCommand, runFormatterCommand, runFormatterTextCommand, runPackageFormatterCheckCommand, runPackageFormatterCommand, runPackageFormatterTextCommand };
