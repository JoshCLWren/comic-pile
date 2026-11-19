"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const ceReactionsPreSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPreSteps;
const ceReactionsPostSteps_jsdom_living_helpers_custom_elements =
  require("../../jsdom/living/helpers/custom-elements.js").ceReactionsPostSteps;
const CSSStyleSheet = require("./CSSStyleSheet.js");
const ctorRegistrySymbol = utils.ctorRegistrySymbol;
const DocumentFragment = require("./DocumentFragment.js");

const interfaceName = "ShadowRoot";

const $interfaceDescriptor = utils.createInterfaceDescriptor(
  () => DocumentFragment.interfaceDescriptor,
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
  throw new globalObject.TypeError(`${context} is not of type 'ShadowRoot'.`);
};

function makeWrapper(globalObject, newTarget) {
  let proto;
  if (newTarget !== undefined) {
    proto = newTarget.prototype;
  }

  if (!utils.isObject(proto)) {
    proto = globalObject[ctorRegistrySymbol]["ShadowRoot"].prototype;
  }

  return Object.create(proto);
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
  DocumentFragment._internalSetup(wrapper, globalObject);
};
exports._initializeObservableArrays = (impl, globalObject) => {
  utils.initObservableArray(impl, globalObject, "adoptedStyleSheets", (value) => {
    value = CSSStyleSheet.convert(globalObject, value, {
      context: `Failed to modify the 'adoptedStyleSheets' observable array on 'ShadowRoot': The provided value`,
    });

    return value;
  });
};
exports.setup = (wrapper, globalObject, constructorArgs = [], privateData = {}) => {
  privateData.wrapper = wrapper;

  exports._internalSetup(wrapper, globalObject);
  const impl = new Impl.implementation(globalObject, constructorArgs, privateData);

  utils.registerWrapper(wrapper, impl, $interfaceDescriptor);
  impl[utils.wrapperSymbol] = wrapper;
  exports._initializeObservableArrays(impl, globalObject);
  if (Impl.init) {
    Impl.init(impl);
  }
  return wrapper;
};

exports.new = (globalObject, newTarget) => {
  const wrapper = makeWrapper(globalObject, newTarget);

  exports._internalSetup(wrapper, globalObject);
  const impl = Object.create(Impl.implementation.prototype);

  utils.registerWrapper(wrapper, impl, $interfaceDescriptor);
  impl[utils.wrapperSymbol] = wrapper;
  exports._initializeObservableArrays(impl, globalObject);
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
  class ShadowRoot extends globalObject.DocumentFragment {
    constructor() {
      throw new globalObject.TypeError("Illegal constructor");
    }

    get mode() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get mode");
      return utils.tryWrapperForImpl($impl["mode"]);
    }

    get host() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get host");
      return utils.tryWrapperForImpl($impl["host"]);
    }

    get innerHTML() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get innerHTML");

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        return $impl["innerHTML"];
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    set innerHTML(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set innerHTML");

      V = conversions["DOMString"](V, {
        context: `Failed to set the 'innerHTML' property on 'ShadowRoot': The provided value`,
        globals: globalObject,
        treatNullAsEmptyString: true,
      });

      ceReactionsPreSteps_jsdom_living_helpers_custom_elements(globalObject);
      try {
        $impl["innerHTML"] = V;
      } finally {
        ceReactionsPostSteps_jsdom_living_helpers_custom_elements(globalObject);
      }
    }

    get activeElement() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get activeElement");
      return utils.tryWrapperForImpl($impl["activeElement"]);
    }

    get styleSheets() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get styleSheets");
      return utils.getSameObject(this, "styleSheets", () => {
        return utils.tryWrapperForImpl($impl["styleSheets"]);
      });
    }

    get adoptedStyleSheets() {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "get adoptedStyleSheets");
      return utils.getObservableArray($impl, "adoptedStyleSheets");
    }

    set adoptedStyleSheets(V) {
      const $impl = $requireImpl(this ?? globalObject, globalObject, "set adoptedStyleSheets");
      let value = V;
      if (!utils.isObject(value)) {
        throw new globalObject.TypeError(
          `Failed to set the 'adoptedStyleSheets' property on 'ShadowRoot': The provided value is not an iterable object.`,
        );
      } else {
        const V = [];
        const tmp = value;
        for (let nextItem of tmp) {
          nextItem = CSSStyleSheet.convert(globalObject, nextItem, {
            context: `Failed to set the 'adoptedStyleSheets' property on 'ShadowRoot': The provided value's element`,
          });

          V.push(nextItem);
        }
        value = V;
      }

      utils.setObservableArray($impl, "adoptedStyleSheets", value);
    }
  }
  Object.defineProperties(ShadowRoot.prototype, {
    mode: { enumerable: true },
    host: { enumerable: true },
    innerHTML: { enumerable: true },
    activeElement: { enumerable: true },
    styleSheets: { enumerable: true },
    adoptedStyleSheets: { enumerable: true },
    [Symbol.toStringTag]: { value: "ShadowRoot", configurable: true },
  });
  ctorRegistry[interfaceName] = ShadowRoot;

  Object.defineProperty(globalObject, interfaceName, {
    configurable: true,
    writable: true,
    value: ShadowRoot,
  });
};

const Impl = require("../../jsdom/living/nodes/ShadowRoot-impl.js");
