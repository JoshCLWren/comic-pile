import { substringBefore } from './string.js';
export class ConfigurationError extends Error {
}
export class ConfigurationValidationError extends Error {
    errors;
    constructor(errors) {
        super(errors.join('\n'));
        this.errors = errors;
    }
}
export class CompilerError extends Error {
}
export class LoaderError extends Error {
}
export const isKnownError = (error) => error instanceof ConfigurationError ||
    error instanceof CompilerError ||
    error instanceof LoaderError ||
    error instanceof ConfigurationValidationError;
export const hasErrorCause = (error) => error.cause instanceof Error;
export const isConfigurationError = (error) => error instanceof ConfigurationError;
export const isModuleNotFoundError = (error) => 'code' in error && error.code === 'MODULE_NOT_FOUND';
export const isLoaderError = (error) => error instanceof LoaderError;
export const formatCauseMessage = (error, cwd) => {
    let root = error;
    while (root.cause instanceof Error)
        root = root.cause;
    return substringBefore(root.message, '\n').replace(`${cwd}/`, '');
};
export const getKnownErrors = (error) => {
    if (error instanceof ConfigurationValidationError)
        return Array.from(error.errors, message => new Error(message));
    return [error];
};
