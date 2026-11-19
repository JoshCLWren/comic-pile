"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const ceReactionsPreSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPreSteps;
const ceReactionsPostSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPostSteps;
const ctorRegistrySymbol = utils.ctorRegistrySymbol;
const CSSStyleDeclaration = require("./CSSStyleDeclaration.js");

const interfaceName = "CSSPositionTryDescriptors";

const $interfaceDescriptor = utils.createInterfaceDescriptor(
  () => CSSStyleDeclaration.interfaceDescriptor,
);
exports.interfaceDescriptor = $interfaceDescriptor;

function $requireImpl(wrapper, globalObject, context) {
  return utils.requireImplForWrapper(
    wrapper,
    $interfaceDescriptor,
    globalObject,
    interfaceName,
    context,
  );
}

exports.is = (value) => {
  return utils.implForWrapperWithInterface(value, $interfaceDescriptor) !== null;
};
exports.isImpl = (value) => {
  return utils.isObject(value) && value instanceof Impl.implementation;
};
exports.convert = (globalObject, value, { context = "The provided value" } = {}) => {
  const impl = utils.implForWrapperWithInterface(value, $interfaceDescriptor);
  if (impl !== null) {
    return impl;
  }
  throw new globalObject.TypeError(`${context} is not of type 'CSSPositionTryDescriptors'.`);
};

function makeWrapper(globalObject, newTarget) {
  let proto;
  if (newTarget !== undefined) {
    proto = newTarget.prototype;
  }

  if (!utils.isObject(proto)) {
    proto = globalObject[ctorRegistrySymbol]["CSSPositionTryDescriptors"].prototype;
  }

  return Object.create(proto);
}

function makeProxy(wrapper, impl, globalObject) {
  let proxyHandler = proxyHandlerCache.get(globalObject);
  if (proxyHandler === undefined) {
    proxyHandler = new ProxyHandler(globalObject);
    proxyHandlerCache.set(globalObject, proxyHandler);
  }
  // The target needs an implementation for proxy traps, but only the final proxy gets the interface brand.
  utils.registerWrapper(wrapper, impl, undefined);
  return new Proxy(wrapper, proxyHandler);
}

exports.create = (globalObject, constructorArgs, privateData) => {
  const wrapper = makeWrapper(globalObject);
  return exports.setup(wrapper, globalObject, constructorArgs, privateData);
};

exports.createImpl = (globalObject, constructorArgs, privateData) => {
  const wrapper = exports.create(globalObject, constructorArgs, privateData);
  return utils.implForWrapper(wrapper);
};

exports._internalSetup = (wrapper, globalObject) => {
  CSSStyleDeclaration._internalSetup(wrapper, globalObject);
};

exports.setup = (wrapper, globalObject, constructorArgs = [], privateData = {}) => {
  privateData.wrapper = wrapper;

  exports._internalSetup(wrapper, globalObject);
  const impl = new Impl.implementation(globalObject, constructorArgs, privateData);

  wrapper = makeProxy(wrapper, impl, globalObject);

  utils.registerWrapper(wrapper, impl, $interfaceDescriptor);
  impl[utils.wrapperSymbol] = wrapper;
  if (Impl.init) {
    Impl.init(impl);
  }
  return wrapper;
};

exports.new = (globalObject, newTarget) => {
  let wrapper = makeWrapper(globalObject, newTarget);

  exports._internalSetup(wrapper, globalObject);
  const impl = Object.create(Impl.implementation.prototype);

  wrapper = makeProxy(wrapper, impl, globalObject);

  utils.registerWrapper(wrapper, impl, $interfaceDescriptor);
  impl[utils.wrapperSymbol] = wrapper;
  if (Impl.init) {
    Impl.init(impl);
  }
  return impl;
};

const exposed = new Set(["Window"]);

exports.install = (globalObject, globalNames) => {
  if (!globalNames.some((globalName) => exposed.has(globalName))) {
    return;
  }

  const ctorRegistry = utils.initCtorRegistry(globalObject);
  class CSSPositionTryDescriptors extends globalObject.CSSStyleDeclaration {
    constructor() {
      throw new globalObject.TypeError("Illegal constructor");
    }

    get "position-anchor"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get position-anchor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("position-anchor");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "position-anchor"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set position-anchor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'position-anchor' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("position-anchor", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get positionAnchor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get positionAnchor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("position-anchor");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set positionAnchor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set positionAnchor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'positionAnchor' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("position-anchor", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "position-area"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get position-area");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("position-area");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "position-area"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set position-area");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'position-area' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("position-area", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get positionArea() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get positionArea");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("position-area");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set positionArea(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set positionArea");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'positionArea' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("position-area", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "align-self"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get align-self");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("align-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "align-self"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set align-self");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'align-self' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("align-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get alignSelf() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get alignSelf");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("align-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set alignSelf(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set alignSelf");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'alignSelf' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("align-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "block-size"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get block-size");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("block-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "block-size"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set block-size");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'block-size' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("block-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get blockSize() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get blockSize");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("block-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set blockSize(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set blockSize");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'blockSize' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("block-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get bottom() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get bottom");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("bottom");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set bottom(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set bottom");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'bottom' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("bottom", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get height() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get height");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("height");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set height(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set height");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'height' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("height", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "inline-size"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inline-size");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inline-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "inline-size"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inline-size");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inline-size' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inline-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get inlineSize() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inlineSize");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inline-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set inlineSize(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inlineSize");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inlineSize' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inline-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get inset() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inset");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set inset(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inset");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inset' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "inset-block"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inset-block");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-block");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "inset-block"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inset-block");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inset-block' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-block", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get insetBlock() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get insetBlock");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-block");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set insetBlock(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set insetBlock");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'insetBlock' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-block", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "inset-block-end"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inset-block-end");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-block-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "inset-block-end"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inset-block-end");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inset-block-end' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-block-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get insetBlockEnd() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get insetBlockEnd");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-block-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set insetBlockEnd(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set insetBlockEnd");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'insetBlockEnd' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-block-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "inset-block-start"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inset-block-start");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-block-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "inset-block-start"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inset-block-start");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inset-block-start' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-block-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get insetBlockStart() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get insetBlockStart");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-block-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set insetBlockStart(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set insetBlockStart");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'insetBlockStart' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-block-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "inset-inline"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inset-inline");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-inline");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "inset-inline"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inset-inline");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inset-inline' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-inline", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get insetInline() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get insetInline");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-inline");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set insetInline(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set insetInline");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'insetInline' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-inline", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "inset-inline-end"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inset-inline-end");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-inline-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "inset-inline-end"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inset-inline-end");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inset-inline-end' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-inline-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get insetInlineEnd() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get insetInlineEnd");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-inline-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set insetInlineEnd(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set insetInlineEnd");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'insetInlineEnd' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-inline-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "inset-inline-start"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get inset-inline-start");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-inline-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "inset-inline-start"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set inset-inline-start");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'inset-inline-start' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-inline-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get insetInlineStart() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get insetInlineStart");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("inset-inline-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set insetInlineStart(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set insetInlineStart");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'insetInlineStart' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("inset-inline-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "justify-self"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get justify-self");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("justify-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "justify-self"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set justify-self");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'justify-self' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("justify-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get justifySelf() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get justifySelf");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("justify-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set justifySelf(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set justifySelf");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'justifySelf' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("justify-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get left() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get left");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("left");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set left(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set left");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'left' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("left", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get margin() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set margin(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-block"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-block");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-block");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-block"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-block");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-block' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-block", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginBlock() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginBlock");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-block");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginBlock(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginBlock");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginBlock' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-block", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-block-end"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-block-end");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-block-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-block-end"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-block-end");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-block-end' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-block-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginBlockEnd() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginBlockEnd");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-block-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginBlockEnd(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginBlockEnd");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginBlockEnd' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-block-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-block-start"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-block-start");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-block-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-block-start"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-block-start");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-block-start' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-block-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginBlockStart() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginBlockStart");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-block-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginBlockStart(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginBlockStart");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginBlockStart' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-block-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-bottom"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-bottom");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-bottom");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-bottom"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-bottom");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-bottom' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-bottom", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginBottom() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginBottom");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-bottom");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginBottom(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginBottom");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginBottom' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-bottom", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-inline"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-inline");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-inline");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-inline"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-inline");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-inline' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-inline", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginInline() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginInline");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-inline");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginInline(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginInline");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginInline' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-inline", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-inline-end"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-inline-end");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-inline-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-inline-end"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-inline-end");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-inline-end' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-inline-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginInlineEnd() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginInlineEnd");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-inline-end");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginInlineEnd(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginInlineEnd");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginInlineEnd' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-inline-end", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-inline-start"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-inline-start");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-inline-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-inline-start"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-inline-start");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-inline-start' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-inline-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginInlineStart() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginInlineStart");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-inline-start");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginInlineStart(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginInlineStart");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginInlineStart' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-inline-start", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-left"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-left");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-left");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-left"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-left");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-left' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-left", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginLeft() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginLeft");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-left");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginLeft(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginLeft");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginLeft' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-left", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-right"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-right");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-right");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-right"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-right");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-right' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-right", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginRight() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginRight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-right");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginRight(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginRight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginRight' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-right", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "margin-top"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get margin-top");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-top");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "margin-top"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set margin-top");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'margin-top' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-top", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get marginTop() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get marginTop");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("margin-top");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set marginTop(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set marginTop");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'marginTop' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("margin-top", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "max-block-size"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get max-block-size");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-block-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "max-block-size"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set max-block-size");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'max-block-size' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-block-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get maxBlockSize() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get maxBlockSize");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-block-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set maxBlockSize(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set maxBlockSize");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'maxBlockSize' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-block-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "max-height"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get max-height");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-height");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "max-height"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set max-height");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'max-height' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-height", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get maxHeight() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get maxHeight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-height");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set maxHeight(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set maxHeight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'maxHeight' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-height", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "max-inline-size"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get max-inline-size");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-inline-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "max-inline-size"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set max-inline-size");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'max-inline-size' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-inline-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get maxInlineSize() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get maxInlineSize");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-inline-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set maxInlineSize(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set maxInlineSize");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'maxInlineSize' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-inline-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "max-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get max-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "max-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set max-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'max-width' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get maxWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get maxWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("max-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set maxWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set maxWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'maxWidth' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("max-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "min-block-size"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get min-block-size");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-block-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "min-block-size"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set min-block-size");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'min-block-size' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-block-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get minBlockSize() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get minBlockSize");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-block-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set minBlockSize(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set minBlockSize");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'minBlockSize' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-block-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "min-height"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get min-height");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-height");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "min-height"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set min-height");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'min-height' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-height", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get minHeight() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get minHeight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-height");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set minHeight(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set minHeight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'minHeight' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-height", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "min-inline-size"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get min-inline-size");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-inline-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "min-inline-size"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set min-inline-size");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'min-inline-size' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-inline-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get minInlineSize() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get minInlineSize");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-inline-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set minInlineSize(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set minInlineSize");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'minInlineSize' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-inline-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "min-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get min-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "min-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set min-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'min-width' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get minWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get minWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("min-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set minWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set minWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'minWidth' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("min-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "place-self"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get place-self");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("place-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "place-self"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set place-self");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'place-self' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("place-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get placeSelf() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get placeSelf");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("place-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set placeSelf(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set placeSelf");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'placeSelf' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("place-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get right() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get right");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("right");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set right(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set right");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'right' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("right", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get top() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get top");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("top");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set top(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set top");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'top' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("top", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get width() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set width(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'width' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "-webkit-align-self"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get -webkit-align-self");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("-webkit-align-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "-webkit-align-self"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set -webkit-align-self");

      V = conversions["DOMString"](V, {
        context: `Failed to set the '-webkit-align-self' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("-webkit-align-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get WebkitAlignSelf() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get WebkitAlignSelf");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("-webkit-align-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set WebkitAlignSelf(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set WebkitAlignSelf");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'WebkitAlignSelf' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("-webkit-align-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get webkitAlignSelf() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get webkitAlignSelf");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("-webkit-align-self");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set webkitAlignSelf(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set webkitAlignSelf");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'webkitAlignSelf' property on 'CSSPositionTryDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("-webkit-align-self", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }
  }
  Object.defineProperties(CSSPositionTryDescriptors.prototype, {
    "position-anchor": { enumerable: true },
    positionAnchor: { enumerable: true },
    "position-area": { enumerable: true },
    positionArea: { enumerable: true },
    "align-self": { enumerable: true },
    alignSelf: { enumerable: true },
    "block-size": { enumerable: true },
    blockSize: { enumerable: true },
    bottom: { enumerable: true },
    height: { enumerable: true },
    "inline-size": { enumerable: true },
    inlineSize: { enumerable: true },
    inset: { enumerable: true },
    "inset-block": { enumerable: true },
    insetBlock: { enumerable: true },
    "inset-block-end": { enumerable: true },
    insetBlockEnd: { enumerable: true },
    "inset-block-start": { enumerable: true },
    insetBlockStart: { enumerable: true },
    "inset-inline": { enumerable: true },
    insetInline: { enumerable: true },
    "inset-inline-end": { enumerable: true },
    insetInlineEnd: { enumerable: true },
    "inset-inline-start": { enumerable: true },
    insetInlineStart: { enumerable: true },
    "justify-self": { enumerable: true },
    justifySelf: { enumerable: true },
    left: { enumerable: true },
    margin: { enumerable: true },
    "margin-block": { enumerable: true },
    marginBlock: { enumerable: true },
    "margin-block-end": { enumerable: true },
    marginBlockEnd: { enumerable: true },
    "margin-block-start": { enumerable: true },
    marginBlockStart: { enumerable: true },
    "margin-bottom": { enumerable: true },
    marginBottom: { enumerable: true },
    "margin-inline": { enumerable: true },
    marginInline: { enumerable: true },
    "margin-inline-end": { enumerable: true },
    marginInlineEnd: { enumerable: true },
    "margin-inline-start": { enumerable: true },
    marginInlineStart: { enumerable: true },
    "margin-left": { enumerable: true },
    marginLeft: { enumerable: true },
    "margin-right": { enumerable: true },
    marginRight: { enumerable: true },
    "margin-top": { enumerable: true },
    marginTop: { enumerable: true },
    "max-block-size": { enumerable: true },
    maxBlockSize: { enumerable: true },
    "max-height": { enumerable: true },
    maxHeight: { enumerable: true },
    "max-inline-size": { enumerable: true },
    maxInlineSize: { enumerable: true },
    "max-width": { enumerable: true },
    maxWidth: { enumerable: true },
    "min-block-size": { enumerable: true },
    minBlockSize: { enumerable: true },
    "min-height": { enumerable: true },
    minHeight: { enumerable: true },
    "min-inline-size": { enumerable: true },
    minInlineSize: { enumerable: true },
    "min-width": { enumerable: true },
    minWidth: { enumerable: true },
    "place-self": { enumerable: true },
    placeSelf: { enumerable: true },
    right: { enumerable: true },
    top: { enumerable: true },
    width: { enumerable: true },
    "-webkit-align-self": { enumerable: true },
    WebkitAlignSelf: { enumerable: true },
    webkitAlignSelf: { enumerable: true },
    [Symbol.toStringTag]: { value: "CSSPositionTryDescriptors", configurable: true },
    [Symbol.iterator]: {
      value: globalObject.Array.prototype[Symbol.iterator],
      configurable: true,
      writable: true,
    },
  });
  ctorRegistry[interfaceName] = CSSPositionTryDescriptors;

  Object.defineProperty(globalObject, interfaceName, {
    configurable: true,
    writable: true,
    value: CSSPositionTryDescriptors,
  });
};

const proxyHandlerCache = new WeakMap();
class ProxyHandler {
  constructor(globalObject) {
    this._globalObject = globalObject;
  }

  get(target, P, receiver) {
    if (typeof P === "symbol") {
      return Reflect.get(target, P, receiver);
    }
    const impl = utils.implForWrapper(target);

    if (utils.isArrayIndexPropName(P)) {
      const index = P >>> 0;

      if (impl[utils.supportsPropertyIndex](index)) {
        const indexedValue = impl.item(index);
        return utils.tryWrapperForImpl(indexedValue);
      }
    }

    return Reflect.get(target, P, receiver);
  }

  has(target, P) {
    if (typeof P === "symbol") {
      return Reflect.has(target, P);
    }
    const desc = this.getOwnPropertyDescriptor(target, P);
    if (desc !== undefined) {
      return true;
    }
    const parent = Object.getPrototypeOf(target);
    if (parent !== null) {
      return Reflect.has(parent, P);
    }
    return false;
  }

  ownKeys(target) {
    const impl = utils.implForWrapper(target);
    const keys = new Set();

    for (const key of impl[utils.supportedPropertyIndices]) {
      keys.add(`${key}`);
    }

    for (const key of Reflect.ownKeys(target)) {
      keys.add(key);
    }
    return [...keys];
  }

  getOwnPropertyDescriptor(target, P) {
    if (typeof P === "symbol") {
      return Reflect.getOwnPropertyDescriptor(target, P);
    }
    const impl = utils.implForWrapper(target);

    if (utils.isArrayIndexPropName(P)) {
      const index = P >>> 0;

      if (impl[utils.supportsPropertyIndex](index)) {
        const indexedValue = impl.item(index);
        return {
          writable: false,
          enumerable: true,
          configurable: true,
          value: utils.tryWrapperForImpl(indexedValue),
        };
      }
    }

    return Reflect.getOwnPropertyDescriptor(target, P);
  }

  set(target, P, V, receiver) {
    if (typeof P === "symbol") {
      return Reflect.set(target, P, V, receiver);
    }
    const impl = utils.implForWrapper(target);
    // The `receiver` argument refers to the Proxy exotic object or an object
    // that inherits from it, whereas `target` refers to the Proxy target:
    if (utils.wrapperForImpl(impl) === receiver) {
      const globalObject = this._globalObject;
    }
    let ownDesc;

    if (utils.isArrayIndexPropName(P)) {
      const index = P >>> 0;

      if (impl[utils.supportsPropertyIndex](index)) {
        const indexedValue = impl.item(index);
        ownDesc = {
          writable: false,
          enumerable: true,
          configurable: true,
          value: utils.tryWrapperForImpl(indexedValue),
        };
      }
    }

    if (ownDesc === undefined) {
      ownDesc = Reflect.getOwnPropertyDescriptor(target, P);
    }
    return utils.ordinarySetWithOwnDescriptor(target, P, V, receiver, ownDesc);
  }

  defineProperty(target, P, desc) {
    if (typeof P === "symbol") {
      return Reflect.defineProperty(target, P, desc);
    }
    const impl = utils.implForWrapper(target);

    const globalObject = this._globalObject;

    if (utils.isArrayIndexPropName(P)) {
      return false;
    }

    return Reflect.defineProperty(target, P, desc);
  }

  deleteProperty(target, P) {
    if (typeof P === "symbol") {
      return Reflect.deleteProperty(target, P);
    }
    const impl = utils.implForWrapper(target);

    const globalObject = this._globalObject;

    if (utils.isArrayIndexPropName(P)) {
      const index = P >>> 0;
      return !impl[utils.supportsPropertyIndex](index);
    }

    return Reflect.deleteProperty(target, P);
  }

  preventExtensions() {
    return false;
  }
}

const Impl = require("../../jsdom/living/css/CSSPositionTryDescriptors-impl.js");
