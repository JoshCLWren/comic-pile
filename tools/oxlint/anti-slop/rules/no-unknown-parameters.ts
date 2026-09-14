import { defineRule } from "@oxlint/plugins";
import type { ESTree } from "@oxlint/plugins";

import {
  containsUnknownType,
  functionParameterBindingName,
  functionParameterTypeAnnotation,
  isInsideCatchClause,
  isTestFile,
  isReturnTypeBoolean,
  hasGenericUnknownDefault,
} from "../shared/function-parameters.ts";

type ParameterOwner =
  | ESTree.ArrowFunctionExpression
  | ESTree.Function
  | ESTree.TSCallSignatureDeclaration
  | ESTree.TSConstructSignatureDeclaration
  | ESTree.TSConstructorType
  | ESTree.TSFunctionType
  | ESTree.TSMethodSignature;

const KNOWN_BOUNDARY_FUNCTIONS = new Set([
  "classTag", "cast", "objectToString",
  "getApiErrorStatus", "getApiErrorDetail",
  "errorMessage", "normalizeQueryError", "processQueue",
  "isAmbiguousNetworkFailure", "isAuthenticationMutationFailure",
  "isDefinitiveAuthenticationFailure", "isSupportedTheme",
  "isGenericNetworkError", "getConflictMessage", "toText",
  "pickString", "pickBoolean",
]);

const KNOWN_BOUNDARY_FUNCTION_NAMES = new Set([
  "error", "err", "reason", "cause",
  "value", "old",
]);

function getFunctionName(node: ParameterOwner): string {
  if ("id" in node && node.id) return node.id.name;
  if (node.type === "ArrowFunctionExpression") return "<arrow>";
  if ("name" in node) return String((node as any).name);
  return "<anonymous>";
}

function isCatchCallback(node: ParameterOwner, context: ESTree.RuleContext): boolean {
  const source = context.sourceCode.getText(node);
  return source.includes(".catch(") || source.includes("=> Promise.reject");
}

function isTypePredicateSubject(owner: ParameterOwner, parameterName: string): boolean {
  const predicate = owner.returnType?.typeAnnotation;
  return (
    predicate?.type === "TSTypePredicate" &&
    predicate.parameterName.type === "Identifier" &&
    predicate.parameterName.name === parameterName
  );
}

function isKnownBoundaryFunction(funcName: string): boolean {
  return KNOWN_BOUNDARY_FUNCTIONS.has(funcName);
}

const FRAMEWORK_CALLBACK_NAMES = new Set([
  "useCallback", "useEffect", "useReducer", "useMemo", "useRef",
  "setQueryData", "setQueryDataIfFresh", "setPages", "setState",
]);

function isFrameworkCallback(node: ParameterOwner): boolean {
  const parent = (node as ESTree.Node & { parent?: ESTree.Node }).parent;
  if (!parent) return false;

  if (parent.type === "CallExpression") {
    const callee = parent.callee;
    if (callee.type === "MemberExpression") {
      const property = callee.property;
      if (property.type === "Identifier") {
        if (property.name === "catch") return true;
        if (FRAMEWORK_CALLBACK_NAMES.has(property.name)) return true;
        if (callee.object.type === "MemberExpression" && callee.object.property.type === "Identifier" && callee.object.property.name === "use") return true;
      }
    }
    if (callee.type === "Identifier" && FRAMEWORK_CALLBACK_NAMES.has(callee.name)) return true;
  }

  if (parent.type === "Property" || parent.type === "PropertyDefinition") {
    const grandparent = (parent as ESTree.Node & { parent?: ESTree.Node }).parent;
    if (grandparent?.type === "ObjectExpression") return true;
  }

  return false;
}

function isTypeDefinition(node: ParameterOwner): boolean {
  return (
    node.type === "TSFunctionType" ||
    node.type === "TSCallSignatureDeclaration" ||
    node.type === "TSConstructorType"
  );
}

function isTrustBoundary(
  node: ParameterOwner,
  parameter: ESTree.ParamPattern,
  context: ESTree.RuleContext,
  funcName: string,
): boolean {
  const filename = context.getFilename();
  const annotation = functionParameterTypeAnnotation(parameter);
  if (!annotation) return false;

  const name = functionParameterBindingName(parameter, context.sourceCode);

  if (isInsideCatchClause(node)) return true;
  if (isTestFile(filename)) return true;
  if (isReturnTypeBoolean(node.returnType) && containsUnknownType(annotation.typeAnnotation)) return true;
  if (hasGenericUnknownDefault(node.typeParameters)) return true;
  if (isKnownBoundaryFunction(funcName)) return true;
  if (isFrameworkCallback(node)) return true;
  if (isCatchCallback(node, context)) return true;
  if (isTypeDefinition(node)) return true;
  if (KNOWN_BOUNDARY_FUNCTION_NAMES.has(name)) return true;

  return false;
}

/** Disallow unknown inputs except legitimate trust-boundary signatures. */
export const noUnknownParametersRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow explicitly unknown function parameters except trust-boundary signatures (type guards, catch clauses, generic decoders, test doubles, framework callbacks); decode unknown input at its I/O boundary instead.",
    },
    messages: {
      unknownParameter:
        "Parameter `{{parameter}}` leaves input unparsed. Accept a named domain type; run the expected schema or parser at the I/O boundary before calling this function.",
    },
  },
  createOnce(context) {
    const checkParameters = (node: ParameterOwner) => {
      const funcName = getFunctionName(node);
      for (const parameter of node.params) {
        const annotation = functionParameterTypeAnnotation(parameter);
        if (annotation === null || annotation === undefined) continue;
        if (!containsUnknownType(annotation.typeAnnotation)) continue;
        const name = functionParameterBindingName(parameter, context.sourceCode);
        if (name === "cause" || isTypePredicateSubject(node, name) || isTrustBoundary(node, parameter, context, funcName)) continue;
        context.report({
          node: annotation.typeAnnotation,
          messageId: "unknownParameter",
          data: { parameter: name },
        });
      }
    };

    return {
      ArrowFunctionExpression: checkParameters,
      FunctionDeclaration: checkParameters,
      FunctionExpression: checkParameters,
      TSCallSignatureDeclaration: checkParameters,
      TSConstructSignatureDeclaration: checkParameters,
      TSConstructorType: checkParameters,
      TSDeclareFunction: checkParameters,
      TSEmptyBodyFunctionExpression: checkParameters,
      TSFunctionType: checkParameters,
      TSMethodSignature: checkParameters,
    };
  },
});
