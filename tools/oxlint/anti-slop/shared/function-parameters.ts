import type { ESTree, SourceCode } from "@oxlint/plugins";

export type FunctionParameter = ESTree.ParamPattern;

/** Return whether a type is or contains TypeScript's absorbing unknown top type. */
export function containsUnknownType(type: ESTree.TSType): boolean {
	if (type.type === "TSUnknownKeyword") return true;
	if (type.type === "TSParenthesizedType") return containsUnknownType(type.typeAnnotation);
	return type.type === "TSUnionType" && type.types.some(containsUnknownType);
}

/** Return the TypeScript annotation attached to a function parameter or its wrapped binding. */
export function functionParameterTypeAnnotation(
	parameter: FunctionParameter,
): ESTree.TSTypeAnnotation | null | undefined {
	if (parameter.type === "TSParameterProperty") {
		return functionParameterTypeAnnotation(parameter.parameter);
	}
	if (parameter.type === "RestElement") {
		return parameter.typeAnnotation ?? functionParameterTypeAnnotation(parameter.argument);
	}
	if (parameter.type === "AssignmentPattern") {
		return parameter.typeAnnotation ?? functionParameterTypeAnnotation(parameter.left);
	}
	return parameter.typeAnnotation;
}

/** Return only a function parameter's local binding, excluding its annotation and default value. */
export function functionParameterBindingName(
	parameter: FunctionParameter,
	sourceCode: SourceCode,
): string {
	if (parameter.type === "TSParameterProperty") {
		return functionParameterBindingName(parameter.parameter, sourceCode);
	}
	if (parameter.type === "AssignmentPattern") {
		return functionParameterBindingName(parameter.left, sourceCode);
	}
	if (parameter.type === "RestElement") {
		return functionParameterBindingName(parameter.argument, sourceCode);
	}
	if (parameter.type === "Identifier") return parameter.name;

	const sourceText = sourceCode.getText(parameter);
	const annotationStart = parameter.typeAnnotation?.start;
	return annotationStart === undefined
		? sourceText
		: sourceText.slice(0, annotationStart - parameter.start).trimEnd();
}

/** Check if a node is directly inside a catch clause by walking the parent chain. */
export function isInsideCatchClause(node: ESTree.Node): boolean {
	let current: ESTree.Node | undefined = node as ESTree.Node & { parent?: ESTree.Node };
	while (current) {
		if (current.type === "CatchClause") return true;
		current = (current as ESTree.Node & { parent?: ESTree.Node }).parent;
	}
	return false;
}

/** Check if the function node is in a test/unit directory. */
export function isTestFile(filename: string): boolean {
	return /[/\\](test|unit)[/\\]/.test(filename);
}

/** Check if the return type annotation is boolean. */
export function isReturnTypeBoolean(returnType: ESTree.TSTypeAnnotation | null | undefined): boolean {
	if (!returnType) return false;
	return returnType.typeAnnotation.type === "TSBooleanKeyword";
}

/** Check if any type parameter has a default of unknown. */
export function hasGenericUnknownDefault(
	typeParameters: ESTree.TSTypeParameterDeclaration | null | undefined,
): boolean {
	if (!typeParameters) return false;
	return typeParameters.params.some((param) => {
		if (param.type === "TSTypeParameter") {
			return param.default?.type === "TSUnknownKeyword";
		}
		return false;
	});
}
