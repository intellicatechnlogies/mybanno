(() => {
  if (document.body.dataset.adminSession !== '1') return;

  const idleLimit = 30 * 60 * 1000;
  let timer;
  const resetTimer = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      window.location.assign(document.body.dataset.adminLogoutUrl);
    }, idleLimit);
  };

  ['click', 'keydown', 'mousemove', 'scroll', 'touchstart'].forEach((eventName) => {
    document.addEventListener(eventName, resetTimer, { passive: true });
  });
  resetTimer();
})();