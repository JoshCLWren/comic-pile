function limitConcurrency(task, maximum) {
  const waiting = [];
  let running = 0;
  return async (...args) => {
    if (running < maximum) {
      running += 1;
    } else {
      await new Promise((resolve) => waiting.push(resolve));
    }
    try {
      return await task(...args);
    } finally {
      const next = waiting.shift();
      if (next) {
        next();
      } else {
        running -= 1;
      }
    }
  };
}
export {
  limitConcurrency
};
