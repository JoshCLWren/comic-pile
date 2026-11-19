import { Visitor } from 'oxc-parser';
import { toModule, toDependency } from '../../util/input.js';
import { findProperty, getPropertyKey, getStringValues } from '../../typescript/ast-helpers.js';
import { getStringValue } from '../../typescript/ast-nodes.js';
import { isInternal } from '../../util/path.js';
import { getDependenciesFromConfig } from '../babel/index.js';
import { importSettingKinds, toParser } from './helpers.js';
const isParserObjectExpression = (node) => {
    for (const prop of node.properties) {
        if (prop.type === 'SpreadElement')
            return true;
        const key = getPropertyKey(prop);
        if (key === 'parse' || key === 'parseForESLint')
            return true;
    }
    return false;
};
const getInputsFromSettingsAST = (program) => {
    const inputs = [];
    const addResolver = (kind, resolver) => {
        if (!resolver || resolver === 'node' || isInternal(resolver))
            return;
        const dep = kind === 'resolver' ? `eslint-import-resolver-${resolver}` : resolver;
        inputs.push(toModule(dep, { optional: true }));
    };
    const addParser = (name) => {
        if (name)
            inputs.push(toParser(name));
    };
    const addResolvers = (kind, node) => {
        if (node?.type === 'ArrayExpression') {
            for (const element of node.elements)
                addResolvers(kind, element);
        }
        else if (node?.type === 'ObjectExpression') {
            if (kind === 'resolver' && findProperty(node, 'name') && findProperty(node, 'resolver'))
                return;
            for (const prop of node.properties) {
                if (prop.type === 'Property')
                    addResolver(kind, getPropertyKey(prop));
            }
        }
        else {
            addResolver(kind, getStringValue(node));
        }
    };
    const visitor = new Visitor({
        ObjectExpression(node) {
            const settingsNode = findProperty(node, 'settings');
            if (settingsNode?.type === 'ObjectExpression') {
                for (const prop of settingsNode.properties ?? []) {
                    if (prop.type !== 'Property')
                        continue;
                    const key = getPropertyKey(prop);
                    const kind = key && importSettingKinds.get(key);
                    if (kind)
                        addResolvers(kind, prop.value);
                }
            }
            const babelOptions = findProperty(node, 'babelOptions');
            if (babelOptions?.type === 'ObjectExpression') {
                const plugins = [...getStringValues(findProperty(babelOptions, 'plugins'))];
                const presets = [...getStringValues(findProperty(babelOptions, 'presets'))];
                for (const input of getDependenciesFromConfig({ plugins, presets }, false))
                    inputs.push(input);
            }
            const parser = findProperty(findProperty(node, 'parserOptions'), 'parser');
            if (parser?.type === 'ObjectExpression') {
                if (isParserObjectExpression(parser))
                    return;
                for (const prop of parser.properties)
                    if (prop.type === 'Property')
                        addParser(getStringValue(prop.value));
            }
            else {
                addParser(getStringValue(parser));
            }
        },
    });
    visitor.visit(program);
    return inputs;
};
export const getInputsFromFlatConfigAST = (program) => [
    ...getInputsFromSettingsAST(program),
    toDependency('eslint-import-resolver-typescript', { optional: true }),
];
