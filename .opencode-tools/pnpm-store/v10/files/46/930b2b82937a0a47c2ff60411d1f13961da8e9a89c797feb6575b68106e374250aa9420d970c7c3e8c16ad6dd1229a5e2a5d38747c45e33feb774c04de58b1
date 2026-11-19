import {
  runFormatterCheckCommand,
  runFormatterCommand,
  runPackageFormatterCheckCommand,
  runPackageFormatterCommand,
  runPackageFormatterTextCommand
} from "./runFormatterCommand.js";
function createCheckCommand(command) {
  return async (options) => await runFormatterCheckCommand(command, options);
}
function createCheckPackageCommand(command) {
  return async (options) => await runPackageFormatterCheckCommand(command, options);
}
function createFormatTextPackageCommand(command) {
  return async (options) => await runPackageFormatterTextCommand(command, options);
}
function createRunCommand(command) {
  return async (options) => await runFormatterCommand(command, options);
}
function createRunPackageCommand(command) {
  return async (options) => await runPackageFormatterCommand(command, options);
}
export {
  createCheckCommand,
  createCheckPackageCommand,
  createFormatTextPackageCommand,
  createRunCommand,
  createRunPackageCommand
};
