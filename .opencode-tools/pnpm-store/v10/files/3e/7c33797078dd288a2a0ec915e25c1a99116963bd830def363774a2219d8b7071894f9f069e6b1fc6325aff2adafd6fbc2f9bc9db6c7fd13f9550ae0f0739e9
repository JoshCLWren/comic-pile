"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const ceReactionsPreSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPreSteps;
const ceReactionsPostSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPostSteps;
const ctorRegistrySymbol = utils.ctorRegistrySymbol;
const CSSStyleDeclaration = require("./CSSStyleDeclaration.js");

const interfaceName = "CSSMarginDescriptors";

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
  throw new globalObject.TypeError(`${context} is not of type 'CSSMarginDescriptors'.`);
};

function makeWrapper(globalObject, newTarget) {
  let proto;
  if (newTarget !== undefined) {
    proto = newTarget.prototype;
  }

  if (!utils.isObject(proto)) {
    proto = globalObject[ctorRegistrySymbol]["CSSMarginDescriptors"].prototype;
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
  class CSSMarginDescriptors extends globalObject.CSSStyleDeclaration {
    constructor() {
      throw new globalObject.TypeError("Illegal constructor");
    }

    get "page-margin-safety"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get page-margin-safety");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("page-margin-safety");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "page-margin-safety"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set page-margin-safety");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'page-margin-safety' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("page-margin-safety", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get pageMarginSafety() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get pageMarginSafety");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("page-margin-safety");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set pageMarginSafety(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set pageMarginSafety");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'pageMarginSafety' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("page-margin-safety", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get background() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get background");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set background(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set background");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'background' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "background-attachment"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get background-attachment");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-attachment");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "background-attachment"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set background-attachment");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'background-attachment' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-attachment", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get backgroundAttachment() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get backgroundAttachment");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-attachment");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set backgroundAttachment(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set backgroundAttachment");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'backgroundAttachment' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-attachment", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "background-color"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get background-color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "background-color"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set background-color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'background-color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get backgroundColor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get backgroundColor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set backgroundColor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set backgroundColor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'backgroundColor' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "background-image"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get background-image");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-image");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "background-image"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set background-image");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'background-image' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-image", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get backgroundImage() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get backgroundImage");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-image");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set backgroundImage(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set backgroundImage");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'backgroundImage' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-image", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "background-position"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get background-position");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-position");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "background-position"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set background-position");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'background-position' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-position", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get backgroundPosition() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get backgroundPosition");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-position");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set backgroundPosition(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set backgroundPosition");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'backgroundPosition' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-position", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "background-repeat"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get background-repeat");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-repeat");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "background-repeat"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set background-repeat");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'background-repeat' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-repeat", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get backgroundRepeat() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get backgroundRepeat");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("background-repeat");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set backgroundRepeat(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set backgroundRepeat");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'backgroundRepeat' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("background-repeat", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get border() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set border(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-bottom"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-bottom");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-bottom"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-bottom");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-bottom' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderBottom() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderBottom");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderBottom(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderBottom");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderBottom' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-bottom-color"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-bottom-color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-bottom-color"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-bottom-color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-bottom-color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderBottomColor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderBottomColor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderBottomColor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderBottomColor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderBottomColor' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-bottom-style"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-bottom-style");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-bottom-style"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-bottom-style");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-bottom-style' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderBottomStyle() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderBottomStyle");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderBottomStyle(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderBottomStyle");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderBottomStyle' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-bottom-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-bottom-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-bottom-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-bottom-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-bottom-width' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderBottomWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderBottomWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-bottom-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderBottomWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderBottomWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderBottomWidth' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-bottom-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-color"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-color"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderColor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderColor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderColor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderColor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderColor' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-left"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-left");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-left"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-left");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-left' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderLeft() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderLeft");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderLeft(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderLeft");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderLeft' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-left-color"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-left-color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-left-color"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-left-color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-left-color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderLeftColor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderLeftColor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderLeftColor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderLeftColor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderLeftColor' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-left-style"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-left-style");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-left-style"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-left-style");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-left-style' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderLeftStyle() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderLeftStyle");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderLeftStyle(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderLeftStyle");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderLeftStyle' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-left-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-left-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-left-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-left-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-left-width' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderLeftWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderLeftWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-left-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderLeftWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderLeftWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderLeftWidth' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-left-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-right"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-right");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-right"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-right");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-right' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderRight() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderRight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderRight(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderRight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderRight' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-right-color"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-right-color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-right-color"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-right-color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-right-color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderRightColor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderRightColor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderRightColor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderRightColor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderRightColor' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-right-style"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-right-style");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-right-style"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-right-style");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-right-style' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderRightStyle() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderRightStyle");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderRightStyle(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderRightStyle");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderRightStyle' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-right-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-right-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-right-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-right-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-right-width' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderRightWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderRightWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-right-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderRightWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderRightWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderRightWidth' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-right-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-top"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-top");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-top"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-top");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-top' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderTop() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderTop");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderTop(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderTop");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderTop' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-top-color"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-top-color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-top-color"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-top-color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-top-color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderTopColor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderTopColor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderTopColor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderTopColor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderTopColor' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-top-style"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-top-style");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-top-style"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-top-style");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-top-style' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderTopStyle() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderTopStyle");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderTopStyle(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderTopStyle");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderTopStyle' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-top-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-top-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-top-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-top-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-top-width' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderTopWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderTopWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-top-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderTopWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderTopWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderTopWidth' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-top-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "border-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get border-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "border-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set border-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'border-width' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get borderWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get borderWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("border-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set borderWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set borderWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'borderWidth' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("border-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get color() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set color(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "counter-increment"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get counter-increment");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("counter-increment");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "counter-increment"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set counter-increment");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'counter-increment' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("counter-increment", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get counterIncrement() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get counterIncrement");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("counter-increment");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set counterIncrement(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set counterIncrement");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'counterIncrement' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("counter-increment", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "counter-reset"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get counter-reset");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("counter-reset");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "counter-reset"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set counter-reset");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'counter-reset' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("counter-reset", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get counterReset() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get counterReset");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("counter-reset");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set counterReset(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set counterReset");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'counterReset' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("counter-reset", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get direction() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get direction");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("direction");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set direction(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set direction");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'direction' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("direction", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get font() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set font(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font", V, "");
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
        context: `Failed to set the 'font-family' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'fontFamily' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'font-size' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'fontSize' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'font-style' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'fontStyle' property on 'CSSMarginDescriptors': The provided value`,
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

    get "font-variant"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get font-variant");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-variant");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "font-variant"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set font-variant");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'font-variant' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-variant", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get fontVariant() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get fontVariant");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("font-variant");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set fontVariant(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set fontVariant");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'fontVariant' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("font-variant", V, "");
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
        context: `Failed to set the 'font-weight' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'fontWeight' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'height' property on 'CSSMarginDescriptors': The provided value`,
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

    get "letter-spacing"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get letter-spacing");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("letter-spacing");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "letter-spacing"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set letter-spacing");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'letter-spacing' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("letter-spacing", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get letterSpacing() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get letterSpacing");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("letter-spacing");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set letterSpacing(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set letterSpacing");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'letterSpacing' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("letter-spacing", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "line-height"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get line-height");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("line-height");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "line-height"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set line-height");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'line-height' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("line-height", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get lineHeight() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get lineHeight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("line-height");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set lineHeight(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set lineHeight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'lineHeight' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("line-height", V, "");
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
        context: `Failed to set the 'margin' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'margin-bottom' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'marginBottom' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'margin-left' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'marginLeft' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'margin-right' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'marginRight' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'margin-top' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'marginTop' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'max-height' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'maxHeight' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'max-width' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'maxWidth' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'min-height' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'minHeight' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'min-width' property on 'CSSMarginDescriptors': The provided value`,
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
        context: `Failed to set the 'minWidth' property on 'CSSMarginDescriptors': The provided value`,
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

    get outline() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get outline");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("outline");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set outline(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set outline");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'outline' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("outline", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "outline-color"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get outline-color");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("outline-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "outline-color"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set outline-color");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'outline-color' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("outline-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get outlineColor() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get outlineColor");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("outline-color");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set outlineColor(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set outlineColor");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'outlineColor' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("outline-color", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "outline-style"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get outline-style");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("outline-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "outline-style"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set outline-style");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'outline-style' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("outline-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get outlineStyle() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get outlineStyle");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("outline-style");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set outlineStyle(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set outlineStyle");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'outlineStyle' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("outline-style", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "outline-width"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get outline-width");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("outline-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "outline-width"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set outline-width");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'outline-width' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("outline-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get outlineWidth() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get outlineWidth");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("outline-width");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set outlineWidth(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set outlineWidth");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'outlineWidth' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("outline-width", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get padding() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get padding");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set padding(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set padding");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'padding' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "padding-bottom"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get padding-bottom");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-bottom");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "padding-bottom"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set padding-bottom");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'padding-bottom' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-bottom", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get paddingBottom() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get paddingBottom");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-bottom");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set paddingBottom(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set paddingBottom");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'paddingBottom' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-bottom", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "padding-left"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get padding-left");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-left");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "padding-left"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set padding-left");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'padding-left' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-left", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get paddingLeft() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get paddingLeft");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-left");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set paddingLeft(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set paddingLeft");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'paddingLeft' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-left", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "padding-right"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get padding-right");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-right");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "padding-right"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set padding-right");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'padding-right' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-right", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get paddingRight() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get paddingRight");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-right");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set paddingRight(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set paddingRight");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'paddingRight' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-right", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "padding-top"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get padding-top");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-top");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "padding-top"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set padding-top");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'padding-top' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-top", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get paddingTop() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get paddingTop");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("padding-top");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set paddingTop(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set paddingTop");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'paddingTop' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("padding-top", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get quotes() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get quotes");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("quotes");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set quotes(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set quotes");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'quotes' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("quotes", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "text-align"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get text-align");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-align");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "text-align"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set text-align");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'text-align' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-align", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get textAlign() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get textAlign");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-align");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set textAlign(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set textAlign");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'textAlign' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-align", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "text-decoration"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get text-decoration");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-decoration");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "text-decoration"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set text-decoration");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'text-decoration' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-decoration", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get textDecoration() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get textDecoration");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-decoration");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set textDecoration(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set textDecoration");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'textDecoration' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-decoration", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "text-indent"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get text-indent");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-indent");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "text-indent"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set text-indent");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'text-indent' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-indent", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get textIndent() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get textIndent");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-indent");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set textIndent(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set textIndent");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'textIndent' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-indent", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "text-transform"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get text-transform");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-transform");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "text-transform"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set text-transform");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'text-transform' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-transform", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get textTransform() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get textTransform");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("text-transform");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set textTransform(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set textTransform");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'textTransform' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("text-transform", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get visibility() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get visibility");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("visibility");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set visibility(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set visibility");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'visibility' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("visibility", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "white-space"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get white-space");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("white-space");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "white-space"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set white-space");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'white-space' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("white-space", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get whiteSpace() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get whiteSpace");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("white-space");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set whiteSpace(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set whiteSpace");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'whiteSpace' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("white-space", V, "");
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
        context: `Failed to set the 'width' property on 'CSSMarginDescriptors': The provided value`,
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

    get "word-spacing"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get word-spacing");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("word-spacing");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "word-spacing"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set word-spacing");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'word-spacing' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("word-spacing", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get wordSpacing() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get wordSpacing");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("word-spacing");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set wordSpacing(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set wordSpacing");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'wordSpacing' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("word-spacing", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get content() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get content");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("content");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set content(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set content");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'content' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("content", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get overflow() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get overflow");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("overflow");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set overflow(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set overflow");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'overflow' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("overflow", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "unicode-bidi"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get unicode-bidi");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("unicode-bidi");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "unicode-bidi"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set unicode-bidi");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'unicode-bidi' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("unicode-bidi", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get unicodeBidi() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get unicodeBidi");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("unicode-bidi");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set unicodeBidi(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set unicodeBidi");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'unicodeBidi' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("unicode-bidi", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "vertical-align"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get vertical-align");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("vertical-align");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "vertical-align"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set vertical-align");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'vertical-align' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("vertical-align", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get verticalAlign() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get verticalAlign");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("vertical-align");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set verticalAlign(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set verticalAlign");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'verticalAlign' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("vertical-align", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get "z-index"() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get z-index");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("z-index");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set "z-index"(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set z-index");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'z-index' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("z-index", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get zIndex() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get zIndex");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl.getPropertyValue("z-index");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set zIndex(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set zIndex");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'zIndex' property on 'CSSMarginDescriptors': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl.setProperty("z-index", V, "");
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }
  }
  Object.defineProperties(CSSMarginDescriptors.prototype, {
    "page-margin-safety": { enumerable: true },
    pageMarginSafety: { enumerable: true },
    background: { enumerable: true },
    "background-attachment": { enumerable: true },
    backgroundAttachment: { enumerable: true },
    "background-color": { enumerable: true },
    backgroundColor: { enumerable: true },
    "background-image": { enumerable: true },
    backgroundImage: { enumerable: true },
    "background-position": { enumerable: true },
    backgroundPosition: { enumerable: true },
    "background-repeat": { enumerable: true },
    backgroundRepeat: { enumerable: true },
    border: { enumerable: true },
    "border-bottom": { enumerable: true },
    borderBottom: { enumerable: true },
    "border-bottom-color": { enumerable: true },
    borderBottomColor: { enumerable: true },
    "border-bottom-style": { enumerable: true },
    borderBottomStyle: { enumerable: true },
    "border-bottom-width": { enumerable: true },
    borderBottomWidth: { enumerable: true },
    "border-color": { enumerable: true },
    borderColor: { enumerable: true },
    "border-left": { enumerable: true },
    borderLeft: { enumerable: true },
    "border-left-color": { enumerable: true },
    borderLeftColor: { enumerable: true },
    "border-left-style": { enumerable: true },
    borderLeftStyle: { enumerable: true },
    "border-left-width": { enumerable: true },
    borderLeftWidth: { enumerable: true },
    "border-right": { enumerable: true },
    borderRight: { enumerable: true },
    "border-right-color": { enumerable: true },
    borderRightColor: { enumerable: true },
    "border-right-style": { enumerable: true },
    borderRightStyle: { enumerable: true },
    "border-right-width": { enumerable: true },
    borderRightWidth: { enumerable: true },
    "border-top": { enumerable: true },
    borderTop: { enumerable: true },
    "border-top-color": { enumerable: true },
    borderTopColor: { enumerable: true },
    "border-top-style": { enumerable: true },
    borderTopStyle: { enumerable: true },
    "border-top-width": { enumerable: true },
    borderTopWidth: { enumerable: true },
    "border-width": { enumerable: true },
    borderWidth: { enumerable: true },
    color: { enumerable: true },
    "counter-increment": { enumerable: true },
    counterIncrement: { enumerable: true },
    "counter-reset": { enumerable: true },
    counterReset: { enumerable: true },
    direction: { enumerable: true },
    font: { enumerable: true },
    "font-family": { enumerable: true },
    fontFamily: { enumerable: true },
    "font-size": { enumerable: true },
    fontSize: { enumerable: true },
    "font-style": { enumerable: true },
    fontStyle: { enumerable: true },
    "font-variant": { enumerable: true },
    fontVariant: { enumerable: true },
    "font-weight": { enumerable: true },
    fontWeight: { enumerable: true },
    height: { enumerable: true },
    "letter-spacing": { enumerable: true },
    letterSpacing: { enumerable: true },
    "line-height": { enumerable: true },
    lineHeight: { enumerable: true },
    margin: { enumerable: true },
    "margin-bottom": { enumerable: true },
    marginBottom: { enumerable: true },
    "margin-left": { enumerable: true },
    marginLeft: { enumerable: true },
    "margin-right": { enumerable: true },
    marginRight: { enumerable: true },
    "margin-top": { enumerable: true },
    marginTop: { enumerable: true },
    "max-height": { enumerable: true },
    maxHeight: { enumerable: true },
    "max-width": { enumerable: true },
    maxWidth: { enumerable: true },
    "min-height": { enumerable: true },
    minHeight: { enumerable: true },
    "min-width": { enumerable: true },
    minWidth: { enumerable: true },
    outline: { enumerable: true },
    "outline-color": { enumerable: true },
    outlineColor: { enumerable: true },
    "outline-style": { enumerable: true },
    outlineStyle: { enumerable: true },
    "outline-width": { enumerable: true },
    outlineWidth: { enumerable: true },
    padding: { enumerable: true },
    "padding-bottom": { enumerable: true },
    paddingBottom: { enumerable: true },
    "padding-left": { enumerable: true },
    paddingLeft: { enumerable: true },
    "padding-right": { enumerable: true },
    paddingRight: { enumerable: true },
    "padding-top": { enumerable: true },
    paddingTop: { enumerable: true },
    quotes: { enumerable: true },
    "text-align": { enumerable: true },
    textAlign: { enumerable: true },
    "text-decoration": { enumerable: true },
    textDecoration: { enumerable: true },
    "text-indent": { enumerable: true },
    textIndent: { enumerable: true },
    "text-transform": { enumerable: true },
    textTransform: { enumerable: true },
    visibility: { enumerable: true },
    "white-space": { enumerable: true },
    whiteSpace: { enumerable: true },
    width: { enumerable: true },
    "word-spacing": { enumerable: true },
    wordSpacing: { enumerable: true },
    content: { enumerable: true },
    overflow: { enumerable: true },
    "unicode-bidi": { enumerable: true },
    unicodeBidi: { enumerable: true },
    "vertical-align": { enumerable: true },
    verticalAlign: { enumerable: true },
    "z-index": { enumerable: true },
    zIndex: { enumerable: true },
    [Symbol.toStringTag]: { value: "CSSMarginDescriptors", configurable: true },
    [Symbol.iterator]: {
      value: globalObject.Array.prototype[Symbol.iterator],
      configurable: true,
      writable: true,
    },
  });
  ctorRegistry[interfaceName] = CSSMarginDescriptors;

  Object.defineProperty(globalObject, interfaceName, {
    configurable: true,
    writable: true,
    value: CSSMarginDescriptors,
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

const Impl = require("../../jsdom/living/css/CSSMarginDescriptors-impl.js");
