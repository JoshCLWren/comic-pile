import { toConfig, toModule, toEntryPath, toDependency, toEntry } from '../../util/input.js';
import { hasDependency } from '../../util/plugin.js';
import { createComponentStyleUrlsVisitor } from '../_component-style-urls/component-style-urls-visitor.js';
import * as karma from '../karma/helpers.js';
const title = 'Angular';
const enablers = ['@angular/cli'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['angular.json'];
const resolveConfig = async (config, options) => {
    if (!config?.projects)
        return [];
    const inputs = new Set();
    for (const project of Object.values(config.projects)) {
        if (!project.architect)
            continue;
        for (const [targetName, target] of Object.entries(project.architect)) {
            const { options: opts, configurations: configs } = target;
            const [packageName] = typeof target.builder === 'string' ? target.builder.split(':') : [];
            if (packageName)
                inputs.add(toDependency(packageName));
            if (opts) {
                if ('tsConfig' in opts && typeof opts.tsConfig === 'string') {
                    inputs.add(toConfig('typescript', opts.tsConfig));
                }
            }
            const defaultEntriesByOption = opts ? entriesByOption(opts) : new Map();
            const entriesByOptionByConfig = new Map(configs ? Object.entries(configs).map(([name, opts]) => [name, entriesByOption(opts)]) : []);
            const productionEntriesByOption = entriesByOptionByConfig.get(PRODUCTION_CONFIG_NAME) ?? new Map();
            const isBuildTarget = targetName === BUILD_TARGET_NAME;
            const toInput = (option, specifier, isProduction) => {
                const opts = { dir: options.cwd, production: isProduction };
                return option === 'polyfills' ? toModule(specifier, opts) : toEntryPath(specifier, opts);
            };
            for (const [configName, entriesByOption] of entriesByOptionByConfig) {
                for (const [option, entries] of entriesByOption) {
                    for (const entry of entries) {
                        inputs.add(toInput(option, entry, isBuildTarget && configName === PRODUCTION_CONFIG_NAME));
                    }
                }
            }
            for (const [option, entries] of defaultEntriesByOption) {
                for (const entry of entries) {
                    inputs.add(toInput(option, entry, isBuildTarget && !productionEntriesByOption.get(option)?.length));
                }
            }
            if (target.builder && isAngularBuilderRefWithName({ builderRef: target.builder, name: 'karma' }) && opts) {
                const karmaBuilderOptions = opts;
                const testFilePatterns = karmaBuilderOptions.include ?? ['**/*.spec.ts'];
                for (const testFilePattern of testFilePatterns) {
                    inputs.add(toEntry(testFilePattern));
                }
                const excludedTestFilePatterns = karmaBuilderOptions.exclude ?? [];
                for (const excludedTestFilePattern of excludedTestFilePatterns) {
                    inputs.add(toEntry(`!${excludedTestFilePattern}`));
                }
                const karmaConfig = karmaBuilderOptions.karmaConfig;
                if (!karmaConfig) {
                    karma
                        .inputsFromPlugins(['karma-jasmine', 'karma-chrome-launcher', 'karma-jasmine-html-reporter', 'karma-coverage'], options.manifest.devDependencies)
                        .forEach(inputs.add, inputs);
                    karma.inputsFromFrameworks(['jasmine']).forEach(inputs.add, inputs);
                }
                if (karmaConfig && !karma.configFiles.includes(karmaConfig)) {
                    inputs.add(toConfig('karma', karmaConfig));
                }
            }
        }
    }
    return Array.from(inputs);
};
const entriesByOption = (opts) => new Map(Object.entries({
    main: 'main' in opts && opts.main && typeof opts.main === 'string' ? [opts.main] : [],
    scripts: 'scripts' in opts && opts.scripts && Array.isArray(opts.scripts)
        ? opts.scripts.map(scriptStringOrObject => typeof scriptStringOrObject === 'string' ? scriptStringOrObject : scriptStringOrObject.input)
        : [],
    styles: 'styles' in opts && opts.styles && Array.isArray(opts.styles)
        ? opts.styles.map(styleStringOrObject => typeof styleStringOrObject === 'string' ? styleStringOrObject : styleStringOrObject.input)
        : [],
    polyfills: 'polyfills' in opts && opts.polyfills
        ? Array.isArray(opts.polyfills)
            ? opts.polyfills
            : [opts.polyfills]
        : [],
    fileReplacements: 'fileReplacements' in opts && opts.fileReplacements && Array.isArray(opts.fileReplacements)
        ? opts.fileReplacements.map(fileReplacement => 'with' in fileReplacement ? fileReplacement.with : fileReplacement.replaceWith)
        : [],
    browser: 'browser' in opts && opts.browser && typeof opts.browser === 'string' ? [opts.browser] : [],
    server: 'server' in opts && opts.server && typeof opts.server === 'string' ? [opts.server] : [],
    ssrEntry: 'ssr' in opts &&
        opts.ssr &&
        typeof opts.ssr === 'object' &&
        'entry' in opts.ssr &&
        typeof opts.ssr.entry === 'string'
        ? [opts.ssr.entry]
        : [],
}));
const isAngularBuilderRefWithName = ({ builderRef, name }) => {
    const [pkg, builderName] = builderRef.split(':');
    return (pkg === '@angular-devkit/build-angular' || pkg === '@angular/build') && builderName === name;
};
const PRODUCTION_CONFIG_NAME = 'production';
const BUILD_TARGET_NAME = 'build';
const isAngularSpecifier = (specifier) => specifier === '@angular/core';
const registerVisitors = ({ ctx, registerVisitor }) => {
    registerVisitor(createComponentStyleUrlsVisitor(ctx, isAngularSpecifier));
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    resolveConfig,
    registerVisitors,
};
export default plugin;
