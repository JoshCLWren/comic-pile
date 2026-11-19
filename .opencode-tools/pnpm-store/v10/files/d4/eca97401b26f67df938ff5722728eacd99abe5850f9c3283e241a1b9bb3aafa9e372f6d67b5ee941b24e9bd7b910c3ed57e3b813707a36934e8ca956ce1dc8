import scss from '../../compilers/scss.js';
import { hasDependency } from '../../util/plugin.js';
import { createComponentStyleUrlsVisitor } from '../_component-style-urls/component-style-urls-visitor.js';
import { createCustomElementVisitor } from '../_custom-elements/custom-element-visitor.js';
import { entry, resolveFromAST } from './resolveFromAST.js';
const title = 'Stencil';
const enablers = ['@stencil/core'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['stencil.config.{ts,js}'];
const production = ['src/**/*.tsx'];
const isStencilSpecifier = (specifier) => specifier === '@stencil/core';
const registerCompilers = ({ hasDependency, registerCompiler }) => {
    if (hasDependency('@stencil/sass'))
        for (const ext of ['.scss', '.sass'])
            registerCompiler({ extension: ext, compiler: scss.compiler });
};
const registerVisitors = ({ ctx, registerVisitor }) => {
    registerVisitor(createCustomElementVisitor(ctx, isStencilSpecifier, { decoratorName: 'Component' }));
    registerVisitor(createComponentStyleUrlsVisitor(ctx, isStencilSpecifier));
};
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    entry,
    production,
    resolveFromAST,
    registerCompilers,
    registerVisitors,
};
export default plugin;
