interface FormatFilesOptions extends Omit<FormatlyOptions, "dryRun"> {
    /**
     * Whether to report which files aren't formatted instead of formatting them.
     */
    check?: boolean;
}
type FormatFilesReport = FormatFilesReportFailure | FormatFilesReportResult | FormatlyReportError;
interface FormatFilesReportFailure extends FormatFilesResultError {
    formatter: Formatter;
    ran: true;
}
interface FormatFilesReportResult extends FormatFilesResultChanged {
    formatter: Formatter;
    ran: true;
}
type FormatFilesResult = FormatFilesResultChanged | FormatFilesResultError;
interface FormatFilesResultChanged {
    changed: string[];
    error?: never;
}
interface FormatFilesResultError {
    changed?: never;
    error: Error;
}
interface FormatlyOptions extends ResolveFormatterOptions {
    cwd?: string;
    /**
     * Whether to report what would run instead of formatting anything.
     */
    dryRun?: boolean;
    /**
     * Pass an explicitly formatter to use instead of automatically detecting
     */
    formatter?: FormatterName;
}
type FormatlyReport = FormatlyReportError | FormatlyReportResult;
interface FormatlyReportChildProcessResult {
    code: null | number;
    runner: "child_process";
    signal: NodeJS.Signals | null;
}
/**
 * The command a formatter would have spawned, when run with dryRun.
 */
interface FormatlyReportDryRunResult {
    args: string[];
    command: string;
    runner: "dry-run";
}
interface FormatlyReportError {
    message: string;
    ran: false;
}
interface FormatlyReportResult {
    formatter: Formatter;
    ran: true;
    result: FormatlyReportChildProcessResult | FormatlyReportDryRunResult | FormatlyReportVirtualResult;
}
interface FormatlyReportVirtualResult {
    /**
     * Exit code the formatter would have exited with as a process.
     */
    code: number;
    runner: "virtual";
}
interface FormatOptions extends Omit<FormatlyOptions, "dryRun"> {
    /**
     * Path the text should be treated as being at, relative to cwd.
     * Formatters use it to infer the parser and apply per-path config overrides.
     */
    filePath: string;
}
type FormatReport = FormatlyReportError | FormatReportFailure | FormatReportResult;
interface FormatReportFailure extends FormatTextResultError {
    formatter: Formatter;
    ran: true;
}
interface FormatReportResult extends FormatTextResultFormatted {
    formatter: Formatter;
    ran: true;
}
interface Formatter {
    checker: FormatterChecker;
    formatText: FormatterTextRunner;
    name: FormatterName;
    runner: FormatterRunner;
    testers: {
        configFile: RegExp;
        /**
         * Matches a package.json script running the formatter's format command.
         * Checked across all formatters before the looser `script`.
         */
        formatScript: RegExp;
        packageKey?: string;
        /**
         * Matches a package.json script mentioning the formatter's name.
         */
        script: RegExp;
    };
}
type FormatterChecker = (options: FormatterCheckerOptions) => Promise<FormatFilesResult>;
interface FormatterCheckerOptions {
    cwd: string;
    /**
     * Absolute paths of the files to check.
     */
    filePaths: string[];
}
type FormatterName = "biome" | "deno" | "dprint" | "oxfmt" | "prettier";
type FormatterRunner = (options: FormatterRunnerOptions) => Promise<FormatlyReportChildProcessResult | FormatlyReportDryRunResult | FormatlyReportVirtualResult>;
interface FormatterRunnerOptions {
    cwd: string;
    /**
     * Whether to resolve the command that would run without spawning it.
     */
    dryRun?: boolean;
    patterns: string[];
}
type FormatterTextRunner = (options: FormatterTextRunnerOptions) => Promise<FormatTextResult>;
interface FormatterTextRunnerOptions {
    cwd: string;
    /**
     * Absolute path the text should be treated as being at.
     */
    filePath: string;
    text: string;
}
type FormatTextResult = FormatTextResultError | FormatTextResultFormatted;
interface FormatTextResultError {
    error: Error;
    formatted?: never;
}
interface FormatTextResultFormatted {
    error?: never;
    formatted: string;
}
interface ResolveFormatterOptions {
    /**
     * Formatter names to detect in order, before any formatters not listed.
     * Unlisted formatters are then detected in their default order.
     */
    order?: FormatterName[];
    /**
     * Directory to stop searching parent directories for a config file at.
     * If not provided, only the working directory is searched.
     */
    stopDirectory?: StopDirectory;
}
type StopDirectory = ((currentDirectory: string) => boolean) | string;

export type { FormatFilesOptions, FormatFilesReport, FormatFilesReportFailure, FormatFilesReportResult, FormatFilesResult, FormatFilesResultChanged, FormatFilesResultError, FormatOptions, FormatReport, FormatReportFailure, FormatReportResult, FormatTextResult, FormatTextResultError, FormatTextResultFormatted, FormatlyOptions, FormatlyReport, FormatlyReportChildProcessResult, FormatlyReportDryRunResult, FormatlyReportError, FormatlyReportResult, FormatlyReportVirtualResult, Formatter, FormatterChecker, FormatterCheckerOptions, FormatterName, FormatterRunner, FormatterRunnerOptions, FormatterTextRunner, FormatterTextRunnerOptions, ResolveFormatterOptions, StopDirectory };
