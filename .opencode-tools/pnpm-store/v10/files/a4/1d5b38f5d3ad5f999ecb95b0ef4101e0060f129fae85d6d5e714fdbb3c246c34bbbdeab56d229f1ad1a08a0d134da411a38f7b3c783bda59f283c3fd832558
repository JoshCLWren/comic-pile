import { FormatlyOptions, Formatter, FormatterChecker, FormatterTextRunner, FormatterRunner } from './types.js';

declare function selectFormatter(cwd: string, { formatter, order, stopDirectory }: FormatlyOptions): Promise<Formatter | {
    readonly checker: FormatterChecker;
    readonly formatText: FormatterTextRunner;
    readonly name: "biome";
    readonly runner: FormatterRunner;
    readonly testers: {
        readonly configFile: RegExp;
        readonly formatScript: RegExp;
        readonly script: RegExp;
    };
} | {
    readonly checker: FormatterChecker;
    readonly formatText: FormatterTextRunner;
    readonly name: "deno";
    readonly runner: FormatterRunner;
    readonly testers: {
        readonly configFile: RegExp;
        readonly formatScript: RegExp;
        readonly script: RegExp;
    };
} | {
    readonly checker: FormatterChecker;
    readonly formatText: FormatterTextRunner;
    readonly name: "dprint";
    readonly runner: FormatterRunner;
    readonly testers: {
        readonly configFile: RegExp;
        readonly formatScript: RegExp;
        readonly script: RegExp;
    };
} | {
    readonly checker: FormatterChecker;
    readonly formatText: FormatterTextRunner;
    readonly name: "oxfmt";
    readonly runner: FormatterRunner;
    readonly testers: {
        readonly configFile: RegExp;
        readonly formatScript: RegExp;
        readonly script: RegExp;
    };
} | {
    readonly checker: FormatterChecker;
    readonly formatText: FormatterTextRunner;
    readonly name: "prettier";
    readonly runner: FormatterRunner;
    readonly testers: {
        readonly configFile: RegExp;
        readonly formatScript: RegExp;
        readonly packageKey: "prettier";
        readonly script: RegExp;
    };
} | undefined>;

export { selectFormatter };
