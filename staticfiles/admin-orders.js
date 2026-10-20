(() => {
  document.querySelectorAll('.order-update-form').forEach((form) => {
    const status = form.elements.namedItem('status');
    const remarks = form.elements.namedItem('remarks');
    const saveButton = form.querySelector('button[type="submit"]');
    if (!status || !remarks || !saveButton) return;

    const originalStatus = status.value;
    const originalRemarks = remarks.value;
    const updateSaveState = () => {
      saveButton.disabled =
        status.value === originalStatus && remarks.value === originalRemarks;
    };

    status.addEventListener('change', updateSaveState);
    remarks.addEventListener('input', updateSaveState);
  });
})();
