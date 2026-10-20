(() => {
  const filter = document.querySelector('.header-filter');
  if (filter) {
    document.addEventListener('click', (event) => {
      if (filter.open && !filter.contains(event.target)) filter.open = false;
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && filter.open) {
        filter.open = false;
        filter.querySelector('summary').focus();
      }
    });
  }

  const minRange = document.getElementById('header-min-range');
  const maxRange = document.getElementById('header-max-range');
  const minField = document.getElementById('header-min-price');
  const maxField = document.getElementById('header-max-price');
  if (!minRange || !maxRange || !minField || !maxField) return;

  const keepOrder = (changed) => {
    let min = Number(minRange.value);
    let max = Number(maxRange.value);
    if (min > max) {
      if (changed === minRange) max = min;
      else min = max;
    }
    minRange.value = min;
    maxRange.value = max;
  };

  minRange.addEventListener('input', () => {
    keepOrder(minRange);
    minField.value = minRange.value;
  });
  maxRange.addEventListener('input', () => {
    keepOrder(maxRange);
    maxField.value = maxRange.value;
  });
  minField.addEventListener('input', () => {
    if (minField.value !== '') minRange.value = minField.value;
    keepOrder(minRange);
  });
  maxField.addEventListener('input', () => {
    if (maxField.value !== '') maxRange.value = maxField.value;
    keepOrder(maxRange);
  });
})();