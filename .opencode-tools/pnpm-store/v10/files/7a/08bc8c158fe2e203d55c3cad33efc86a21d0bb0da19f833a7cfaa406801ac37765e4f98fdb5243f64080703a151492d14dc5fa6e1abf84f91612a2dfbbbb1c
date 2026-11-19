"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const ceReactionsPreSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPreSteps;
const ceReactionsPostSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPostSteps;
const ctorRegistrySymbol = utils.ctorRegistrySymbol;
const CSSStyleDeclaration = require("./CSSStyleDeclaration.js");

const interfaceName = "CSSFontFaceDescriptors";

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
  throw new globalObject.TypeError(`${context} is not of type 'CSSFontFaceDescriptors'.`);
};

function makeWrapper(globalObject, newTarget) {
  let proto;
  if (newTarget !== undefined) {
    proto = newTarget.prototype;
  }

  if (!utils.isObject(proto)) {
    proto = globalObject[ctorRegistrySymbol]["CSSFontFaceDescriptors"].prototype;
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
  class CSSFontFaceDescriptors extends globalObject.CSSStyleDeclaration {
    constructor() {
      throw new globalObject.TypeError("Illegal constructor");
    }

    get "ascent-override"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get ascent-override");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("ascent-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "ascent-override"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set ascent-override");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'ascent-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("ascent-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get ascentOverride() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get ascentOverride");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("ascent-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set ascentOverride(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set ascentOverride");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'ascentOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("ascent-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "descent-override"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get descent-override");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("descent-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "descent-override"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set descent-override");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'descent-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("descent-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get descentOverride() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get descentOverride");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("descent-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set descentOverride(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set descentOverride");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'descentOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("descent-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-display"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-display");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-display");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-display"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-display");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-display' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-display", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontDisplay() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontDisplay");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-display");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontDisplay(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontDisplay");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontDisplay' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-display", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-family"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-family");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-family");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-family"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-family");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-family' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-family", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontFamily() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontFamily");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-family");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontFamily(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontFamily");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontFamily' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-family", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-feature-settings"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-feature-settings");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-feature-settings");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-feature-settings"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-feature-settings");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-feature-settings' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-feature-settings", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontFeatureSettings() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontFeatureSettings");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-feature-settings");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontFeatureSettings(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontFeatureSettings");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontFeatureSettings' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-feature-settings", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-language-override"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-language-override");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-language-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-language-override"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-language-override");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-language-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-language-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontLanguageOverride() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontLanguageOverride");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-language-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontLanguageOverride(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontLanguageOverride");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontLanguageOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-language-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-named-instance"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-named-instance");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-named-instance");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-named-instance"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-named-instance");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-named-instance' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-named-instance", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontNamedInstance() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontNamedInstance");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-named-instance");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontNamedInstance(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontNamedInstance");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontNamedInstance' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-named-instance", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-size"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-size");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-size"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-size");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-size' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontSize() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontSize");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-size");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontSize(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontSize");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontSize' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-size", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-style"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-style");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-style"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-style");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-style' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontStyle() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontStyle");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontStyle(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontStyle");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontStyle' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-variation-settings"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-variation-settings");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-variation-settings");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-variation-settings"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-variation-settings");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-variation-settings' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-variation-settings", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontVariationSettings() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontVariationSettings");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-variation-settings");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontVariationSettings(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontVariationSettings");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontVariationSettings' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-variation-settings", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-weight"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-weight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-weight");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-weight"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-weight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-weight' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-weight", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontWeight() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontWeight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-weight");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontWeight(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontWeight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontWeight' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-weight", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-width' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontWidth' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "line-gap-override"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get line-gap-override");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("line-gap-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "line-gap-override"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set line-gap-override");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'line-gap-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("line-gap-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get lineGapOverride() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get lineGapOverride");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("line-gap-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set lineGapOverride(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set lineGapOverride");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'lineGapOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("line-gap-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "size-adjust"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get size-adjust");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("size-adjust");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "size-adjust"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set size-adjust");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'size-adjust' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("size-adjust", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get sizeAdjust() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get sizeAdjust");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("size-adjust");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set sizeAdjust(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set sizeAdjust");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'sizeAdjust' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("size-adjust", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get src() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get src");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("src");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set src(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set src");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'src' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("src", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "subscript-position-override"() {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "get subscript-position-override",
      );

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("subscript-position-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "subscript-position-override"(V) {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "set subscript-position-override",
      );

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'subscript-position-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("subscript-position-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get subscriptPositionOverride() {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "get subscriptPositionOverride",
      );

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("subscript-position-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set subscriptPositionOverride(V) {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "set subscriptPositionOverride",
      );

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'subscriptPositionOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("subscript-position-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "subscript-size-override"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get subscript-size-override");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("subscript-size-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "subscript-size-override"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set subscript-size-override");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'subscript-size-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("subscript-size-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get subscriptSizeOverride() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get subscriptSizeOverride");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("subscript-size-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set subscriptSizeOverride(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set subscriptSizeOverride");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'subscriptSizeOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("subscript-size-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "superscript-position-override"() {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "get superscript-position-override",
      );

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("superscript-position-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "superscript-position-override"(V) {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "set superscript-position-override",
      );

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'superscript-position-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("superscript-position-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get superscriptPositionOverride() {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "get superscriptPositionOverride",
      );

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("superscript-position-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set superscriptPositionOverride(V) {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "set superscriptPositionOverride",
      );

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'superscriptPositionOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("superscript-position-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "superscript-size-override"() {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "get superscript-size-override",
      );

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("superscript-size-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "superscript-size-override"(V) {
      const $impl = $requireImpl(
        this ?? globalObject,
        globalObject,
        "set superscript-size-override",
      );

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'superscript-size-override' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("superscript-size-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get superscriptSizeOverride() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get superscriptSizeOverride");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("superscript-size-override");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set superscriptSizeOverride(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set superscriptSizeOverride");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'superscriptSizeOverride' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("superscript-size-override", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "unicode-range"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get unicode-range");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("unicode-range");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "unicode-range"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set unicode-range");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'unicode-range' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("unicode-range", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get unicodeRange() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get unicodeRange");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("unicode-range");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set unicodeRange(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set unicodeRange");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'unicodeRange' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("unicode-range", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "font-stretch"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-stretch");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-stretch");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-stretch"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-stretch");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-stretch' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-stretch", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontStretch() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontStretch");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-stretch");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontStretch(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontStretch");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontStretch' property on 'CSSFontFaceDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-stretch", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }
  }
  Object.defineProperties(CSSFontFaceDescriptors.prototype, {
    "ascent-override": { enumerable: true },
    ascentOverride: { enumerable: true },
    "descent-override": { enumerable: true },
    descentOverride: { enumerable: true },
    "font-display": { enumerable: true },
    fontDisplay: { enumerable: true },
    "font-family": { enumerable: true },
    fontFamily: { enumerable: true },
    "font-feature-settings": { enumerable: true },
    fontFeatureSettings: { enumerable: true },
    "font-language-override": { enumerable: true },
    fontLanguageOverride: { enumerable: true },
    "font-named-instance": { enumerable: true },
    fontNamedInstance: { enumerable: true },
    "font-size": { enumerable: true },
    fontSize: { enumerable: true },
    "font-style": { enumerable: true },
    fontStyle: { enumerable: true },
    "font-variation-settings": { enumerable: true },
    fontVariationSettings: { enumerable: true },
    "font-weight": { enumerable: true },
    fontWeight: { enumerable: true },
    "font-width": { enumerable: true },
    fontWidth: { enumerable: true },
    "line-gap-override": { enumerable: true },
    lineGapOverride: { enumerable: true },
    "size-adjust": { enumerable: true },
    sizeAdjust: { enumerable: true },
    src: { enumerable: true },
    "subscript-position-override": { enumerable: true },
    subscriptPositionOverride: { enumerable: true },
    "subscript-size-override": { enumerable: true },
    subscriptSizeOverride: { enumerable: true },
    "superscript-position-override": { enumerable: true },
    superscriptPositionOverride: { enumerable: true },
    "superscript-size-override": { enumerable: true },
    superscriptSizeOverride: { enumerable: true },
    "unicode-range": { enumerable: true },
    unicodeRange: { enumerable: true },
    "font-stretch": { enumerable: true },
    fontStretch: { enumerable: true },
    [Symbol.toStringTag]: { value: "CSSFontFaceDescriptors", configurable: true },
    [Symbol.iterator]: {
      value: globalObject.Array.prototype[Symbol.iterator],
      configurable: true,
      writable: true,
    },
  });
  ctorRegistry[interfaceName] = CSSFontFaceDescriptors;

  Object.defineProperty(globalObject, interfaceName, {
    configurable: true,
    writable: true,
    value: CSSFontFaceDescriptors,
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

const Impl = require("../../jsdom/living/css/CSSFontFaceDescriptors-impl.js");
