"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const UIEventInit = require("./UIEventInit.js");

exports._convertInherit = (globalObject, obj, ret, { context = "The provided value" } = {}) => {
  UIEventInit._convertInherit(globalObject, obj, ret, { context });

  {
    const key = "altKey";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'altKey' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "ctrlKey";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'ctrlKey' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "metaKey";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'metaKey' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierAltGraph";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierAltGraph' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierCapsLock";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierCapsLock' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierFn";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierFn' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierFnLock";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierFnLock' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierHyper";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierHyper' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierNumLock";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierNumLock' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierScrollLock";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierScrollLock' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierSuper";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierSuper' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierSymbol";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierSymbol' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "modifierSymbolLock";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'modifierSymbolLock' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "shiftKey";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'shiftKey' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }
};

exports.convert = (globalObject, obj, { context = "The provided value" } = {}) => {
  if (obj !== undefined && typeof obj !== "object" && typeof obj !== "function") {
    throw new globalObject.TypeError(`${context} is not an object.`);
  }

  const ret = Object.create(null);
  exports._convertInherit(globalObject, obj, ret, { context });
  return ret;
};
