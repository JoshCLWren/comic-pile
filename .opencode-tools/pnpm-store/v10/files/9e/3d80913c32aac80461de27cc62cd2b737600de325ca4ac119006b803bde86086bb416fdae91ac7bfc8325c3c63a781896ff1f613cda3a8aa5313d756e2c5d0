"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const EventModifierInit = require("./EventModifierInit.js");

exports._convertInherit = (globalObject, obj, ret, { context = "The provided value" } = {}) => {
  EventModifierInit._convertInherit(globalObject, obj, ret, { context });

  {
    const key = "charCode";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["unsigned long"](value, {
        context: `${context}'s 'charCode' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "code";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["DOMString"](value, {
        context: `${context}'s 'code' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = "";
    }
  }

  {
    const key = "isComposing";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'isComposing' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "key";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["DOMString"](value, {
        context: `${context}'s 'key' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = "";
    }
  }

  {
    const key = "keyCode";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["unsigned long"](value, {
        context: `${context}'s 'keyCode' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "location";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["unsigned long"](value, {
        context: `${context}'s 'location' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "repeat";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'repeat' member`,
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
