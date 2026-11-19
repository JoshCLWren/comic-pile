import type { Results } from '../run.ts';
import type { ReporterOptions } from '../types/issues.ts';
import type { ParsedCLIArgs } from './cli-arguments.ts';
import type { MainOptions } from './create-options.ts';
export declare const toReporterOptions: (options: MainOptions, results: Results, args?: ParsedCLIArgs) => ReporterOptions;
export declare const createPreprocessor: (processors: string[]) => Promise<(data: ReporterOptions) => Promise<ReporterOptions>>;
