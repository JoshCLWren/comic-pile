"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const MediaList = require("./MediaList.js");

exports._convertInherit = (globalObject, obj, ret, { context = "The provided value" } = {}) => {
  {
    const key = "baseURL";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      if (value === null || value === undefined) {
        value = null;
      } else {
        value = conversions["DOMString"](value, {
          context: `${context}'s 'baseURL' member`,
          globals: globalObject,
        });
      }
      ret[key] = value;
    } else {
      ret[key] = null;
    }
  }

  {
    const key = "disabled";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'disabled' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "media";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      if (MediaList.is(value)) {
        value = utils.implForWrapper(value);
      } else {
        value = conversions["DOMString"](value, {
          context: `${context}'s 'media' member`,
          globals: globalObject,
        });
      }
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
