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
  if (!form || !actual || !offer || !sale || !error || !name || !otherNameGroup || !otherName || !clothType || !category) return;

  const setupAccumulatingUploads = (inputId, listId, kind) => {
    const input = document.getElementById(inputId);
    const list = document.getElementById(listId);
    if (!input || !list) return;
    let selectedFiles = [];

    const syncInputAndList = () => {
      const transfer = new DataTransfer();
      selectedFiles.forEach((file) => transfer.items.add(file));
      input.files = transfer.files;
      list.replaceChildren();
      selectedFiles.forEach((file, index) => {
        const item = document.createElement('li');
        const filename = document.createElement('span');
        filename.textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.dataset.fileIndex = String(index);
        remove.setAttribute('aria-label', `Remove ${file.name} from pending uploads`);
        remove.textContent = 'Remove';
        item.append(filename, remove);
        list.append(item);
      });
      if (selectedFiles.length) {
        list.setAttribute(
          'aria-label',
          `${selectedFiles.length} ${kind}${selectedFiles.length === 1 ? '' : 's'} selected for upload`,
        );
      } else {
        list.removeAttribute('aria-label');
      }
    };

    input.addEventListener('change', () => {
      const newFiles = Array.from(input.files);
      newFiles.forEach((file) => {
        const alreadySelected = selectedFiles.some(
          (existing) =>
            existing.name === file.name &&
            existing.size === file.size &&
            existing.lastModified === file.lastModified,
        );
        if (!alreadySelected) selectedFiles.push(file);
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

    if (!offer.value && sale.checked) {
      error.textContent = 'Enter an offer price when Sale is selected.';
    } else if (offer.value && (Number.isNaN(offerValue) || offerValue >= actualValue)) {
      error.textContent = 'Offer price must be lower than the actual price.';
    }
    if (error.textContent) {
      error.classList.add('is-visible');
      offer.setCustomValidity(error.textContent);
      return false;
    }
    return true;
  };

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
  validateOffer();
  setupAccumulatingUploads('images', 'selected-images', 'photo');
  setupAccumulatingUploads('videos', 'selected-videos', 'video');
})();