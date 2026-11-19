import { ResolvedCommand } from 'package-manager-detector';
import { FormatterChecker, FormatterTextRunner, FormatterRunner } from '../types.js';
import { FormatCheckCommand, FormatCheckPackageCommand, FormatTextPackageCommand, PackageCommand } from './runFormatterCommand.js';

declare function createCheckCommand(command: FormatCheckCommand): FormatterChecker;
declare function createCheckPackageCommand(command: FormatCheckPackageCommand): FormatterChecker;
declare function createFormatTextPackageCommand(command: FormatTextPackageCommand): FormatterTextRunner;
declare function createRunCommand(command: ResolvedCommand): FormatterRunner;
declare function createRunPackageCommand(command: PackageCommand): FormatterRunner;

export { createCheckCommand, createCheckPackageCommand, createFormatTextPackageCommand, createRunCommand, createRunPackageCommand };
