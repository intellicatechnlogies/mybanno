(() => {
  const idleLimit = 30 * 60 * 1000;
  let timer;
  const resetTimer = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      if (document.body.dataset.adminSession === '1') {
        window.location.assign(document.body.dataset.adminLogoutUrl);
      } else if (document.body.dataset.customerSession === '1') {
        window.location.assign(document.body.dataset.customerLogoutUrl);
      }
    }, idleLimit);
  };

  ['click', 'keydown', 'mousemove', 'scroll', 'touchstart'].forEach((eventName) => {
    document.addEventListener(eventName, resetTimer, { passive: true });
  });
  resetTimer();
})();