(() => {
  const form = document.getElementById('product-form');
  const actual = document.getElementById('actual_price');
  const offer = document.getElementById('offer_price');
  const sale = document.querySelector('input[name="on_offer"]');
  const error = document.getElementById('offer-price-error');
  const name = document.getElementById('name');
  const otherNameGroup = document.getElementById('other-name-group');
  const otherName = document.getElementById('name_other');
  const clothType = document.getElementById('cloth_type');
  const category = document.getElementById('category');
  const occasion = document.getElementById('occasion_category');
  const stockTotal = document.getElementById('stock');
  const panels = document.getElementById('color-size-stock-panels');
  if (!form || !actual || !offer || !sale || !error || !name || !otherNameGroup || !otherName || !clothType || !category || !stockTotal || !panels) return;

  const colorNames = () => Array.from(new Set(
    Array.from(panels.querySelectorAll('.size-color-panel'))
      .filter((panel) => panel.querySelector('input[name="sizes"]').checked)
      .flatMap((panel) => Array.from(panel.querySelectorAll('input[data-color]:checked'))
        .map((input) => input.dataset.color)),
  ));

  const availableColorNames = colorNames;

  const colorValue = (colorName) => {
    const checkbox = Array.from(panels.querySelectorAll('input[data-color]'))
      .find((input) => input.dataset.color === colorName);
    return checkbox?.nextElementSibling?.style.getPropertyValue('--swatch') || '#b8b8b8';
  };

  const updateColorSummaries = () => {
    panels.querySelectorAll('.size-color-panel').forEach((panel) => {
      const selected = Array.from(panel.querySelectorAll('input[data-color]:checked'))
        .map((checkbox) => checkbox.dataset.color);
      const display = panel.querySelector('.color-selection-display');
      if (!display) return;
      display.textContent = selected.length
        ? `Color: ${selected.slice(0, 2).join(', ')}${selected.length > 2 ? ` +${selected.length - 2}` : ''}`
        : 'Color';
    });
  };

  const updateMediaColorChoices = () => {
    const names = availableColorNames();
    form.querySelectorAll('#selected-images select[name="image_colors"]').forEach((select) => {
      const previous = select.value;
      select.replaceChildren(new Option('All colors / no specific color (optional)', ''));
      names.forEach((color) => select.add(new Option(color, color)));
      if (!names.length) {
        const hint = new Option('Select size colors above for photo-specific options', '');
        hint.disabled = true;
        select.add(hint);
      }
      select.value = names.includes(previous) ? previous : '';
      const swatch = select.parentElement.querySelector('.upload-color-swatch');
      if (swatch) {
        swatch.hidden = !select.value;
        if (select.value) swatch.style.setProperty('--swatch', colorValue(select.value));
      }
    });
  };

  const syncTotalStock = () => {
    let total = 0;
    panels.querySelectorAll('.size-color-panel').forEach((panel) => {
      const selectedColors = Array.from(panel.querySelectorAll('input[data-color]:checked'));
      const sizeTotal = panel.querySelector('.size-total-stock');
      const colorTotal = selectedColors.reduce((subtotal, checkbox) => {
        const quantity = panel.querySelector(`[data-stock-color="${CSS.escape(checkbox.dataset.color)}"] input[type="number"]`);
        return subtotal + (Number(quantity?.value) || 0);
      }, 0);
      sizeTotal.hidden = !panel.querySelector('input[name="sizes"]').checked;
      sizeTotal.querySelector('.size-total-quantity').textContent = String(colorTotal);
      if (!panel.querySelector('input[name="sizes"]').checked) return;
      total += colorTotal;
    });
    stockTotal.value = String(total);
  };

  const updateInventoryControls = () => {
    panels.querySelectorAll('.size-color-panel').forEach((panel) => {
      const sizeSelected = panel.querySelector('input[name="sizes"]').checked;
      const colorCheckboxes = Array.from(panel.querySelectorAll('input[data-color]'));
      colorCheckboxes.forEach((checkbox) => {
        const stockRow = Array.from(panel.querySelectorAll('.selected-color-stock'))
          .find((row) => row.dataset.stockColor === checkbox.dataset.color);
        const quantityInput = stockRow.querySelector('input[type="number"]');
        checkbox.disabled = false;
        stockRow.hidden = !checkbox.checked;
        quantityInput.disabled = !sizeSelected || !checkbox.checked;
      });
    });
    updateMediaColorChoices();
    updateColorSummaries();
    syncTotalStock();
  };

  const setupAccumulatingUploads = (inputId, listId, kind, withColors = false) => {
    const input = document.getElementById(inputId);
    const list = document.getElementById(listId);
    if (!input || !list) return;
    const selectedFiles = [];
    const syncInputAndList = () => {
      const transfer = new DataTransfer();
      selectedFiles.forEach(({file}) => transfer.items.add(file));
      input.files = transfer.files;
      list.replaceChildren();
      selectedFiles.forEach(({file, color}, index) => {
        const item = document.createElement('li');
        const filename = document.createElement('span');
        filename.textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
        item.append(filename);
        if (withColors) {
          const colorField = document.createElement('label');
          colorField.className = 'upload-color-field';
          colorField.append(document.createTextNode('Photo color (optional)'));
          const select = document.createElement('select');
          select.name = 'image_colors';
          select.setAttribute('aria-label', `Color for ${file.name}`);
          select.add(new Option('All colors / no specific color (optional)', ''));
          availableColorNames().forEach((value) => select.add(new Option(value, value)));
          if (!availableColorNames().length) {
            const hint = new Option('Select size colors above for photo-specific options', '');
            hint.disabled = true;
            select.add(hint);
          }
          select.value = availableColorNames().includes(color) ? color : '';
          const swatch = document.createElement('i');
          swatch.className = 'upload-color-swatch';
          swatch.hidden = !select.value;
          if (select.value) swatch.style.setProperty('--swatch', colorValue(select.value));
          select.addEventListener('change', () => {
            selectedFiles[index].color = select.value;
            swatch.hidden = !select.value;
            if (select.value) swatch.style.setProperty('--swatch', colorValue(select.value));
          });
          colorField.append(select, swatch);
          item.append(colorField);
        }
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.dataset.fileIndex = String(index);
        remove.setAttribute('aria-label', `Remove ${file.name} from pending uploads`);
        remove.textContent = 'Remove';
        item.append(remove);
        list.append(item);
      });
      if (selectedFiles.length) {
        list.setAttribute('aria-label', `${selectedFiles.length} ${kind}${selectedFiles.length === 1 ? '' : 's'} selected for upload`);
      } else {
        list.removeAttribute('aria-label');
      }
    };
    input.addEventListener('change', () => {
      Array.from(input.files).forEach((file) => {
        if (!selectedFiles.some((entry) => entry.file.name === file.name && entry.file.size === file.size && entry.file.lastModified === file.lastModified)) {
          selectedFiles.push({file, color: ''});
        }
      });
      syncInputAndList();
    });
    list.addEventListener('click', (event) => {
      const removeButton = event.target.closest('[data-file-index]');
      if (!removeButton) return;
      selectedFiles.splice(Number(removeButton.dataset.fileIndex), 1);
      syncInputAndList();
    });
  };

  const toggleOtherName = () => {
    const isOther = name.value === '__other__';
    otherNameGroup.hidden = !isOther;
    otherName.required = isOther;
    if (!isOther) {
      otherName.value = '';
      otherName.setCustomValidity('');
    }
  };

  const setupOtherOption = (select, groupId, inputId) => {
    const group = document.getElementById(groupId);
    const input = document.getElementById(inputId);
    if (!group || !input) return;
    const toggle = () => {
      const isOther = select.value === '__other__';
      group.hidden = !isOther;
      input.required = isOther;
      if (!isOther) {
        input.value = '';
        input.setCustomValidity('');
      }
    };
    select.addEventListener('change', toggle);
    toggle();
  };

  const validateOffer = () => {
    const actualValue = Number(actual.value);
    const offerValue = Number(offer.value);
    offer.max = actual.value || '';
    error.textContent = '';
    error.classList.remove('is-visible');
    offer.setCustomValidity('');
    if (!offer.value && sale.checked) error.textContent = 'Enter an offer price when Sale is selected.';
    else if (offer.value && (Number.isNaN(offerValue) || offerValue >= actualValue)) error.textContent = 'Offer price must be lower than the actual price.';
    if (error.textContent) {
      error.classList.add('is-visible');
      offer.setCustomValidity(error.textContent);
      return false;
    }
    return true;
  };

  panels.addEventListener('change', (event) => {
    if (event.target.matches('input[name="sizes"]') && !event.target.checked) {
      event.target.closest('.size-color-panel').querySelectorAll('input[data-color]').forEach((checkbox) => {
        checkbox.checked = false;
      });
    }
    if (event.target.matches('input[data-color]') && event.target.checked) {
      event.target.closest('.size-color-panel').querySelector('input[name="sizes"]').checked = true;
    }
    if (event.target.matches('input[name="sizes"], input[data-color]')) updateInventoryControls();
  });
  panels.addEventListener('input', (event) => {
    if (event.target.matches('.size-color-search')) {
      const query = event.target.value.trim().toLowerCase();
      event.target.closest('.size-color-panel').querySelectorAll('.color-picker-option').forEach((option) => {
        option.hidden = !option.dataset.colorName.includes(query);
      });
    }
    syncTotalStock();
  });
  document.addEventListener('pointerdown', (event) => {
    panels.querySelectorAll('.color-picker-dropdown[open]').forEach((dropdown) => {
      if (!dropdown.contains(event.target)) dropdown.open = false;
    });
  });

  [actual, offer, sale].forEach((field) => field.addEventListener('input', validateOffer));
  sale.addEventListener('change', validateOffer);
  name.addEventListener('change', toggleOtherName);
  form.addEventListener('submit', (event) => {
    if (!validateOffer()) {
      event.preventDefault();
      offer.focus();
    }
  });
  toggleOtherName();
  setupOtherOption(clothType, 'other-cloth-type-group', 'cloth_type_other');
  setupOtherOption(category, 'other-category-group', 'category_other');
  if (occasion) setupOtherOption(occasion, 'other-occasion-group', 'occasion_category_other');
  updateInventoryControls();
  validateOffer();
  setupAccumulatingUploads('images', 'selected-images', 'photo', true);
  setupAccumulatingUploads('videos', 'selected-videos', 'video');
})();
