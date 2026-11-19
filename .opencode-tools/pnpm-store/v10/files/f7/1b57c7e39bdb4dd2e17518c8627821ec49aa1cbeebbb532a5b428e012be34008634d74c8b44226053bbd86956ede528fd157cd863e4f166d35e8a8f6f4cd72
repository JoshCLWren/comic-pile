"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const EventInit = require("./EventInit.js");

exports._convertInherit = (globalObject, obj, ret, { context = "The provided value" } = {}) => {
  EventInit._convertInherit(globalObject, obj, ret, { context });

  {
    const key = "colno";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["unsigned long"](value, {
        context: `${context}'s 'colno' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "error";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["any"](value, {
        context: `${context}'s 'error' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = null;
    }
  }

  {
    const key = "filename";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["USVString"](value, {
        context: `${context}'s 'filename' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = "";
    }
  }

  {
    const key = "lineno";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["unsigned long"](value, {
        context: `${context}'s 'lineno' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "message";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["DOMString"](value, {
        context: `${context}'s 'message' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = "";
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
