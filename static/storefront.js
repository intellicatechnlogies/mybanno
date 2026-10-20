(() => {
  const grid = document.getElementById('product-grid');
  const loader = document.getElementById('product-loader');
  const modal = document.getElementById('product-modal');
  const imageLightbox = document.querySelector('.product-image-lightbox');
  const hero = document.querySelector('.hero');
  const heroBackgrounds = hero
    ? Array.from(hero.querySelectorAll('.hero-background-image'))
    : [];

  if (grid && heroBackgrounds.length === 2) {
    let activeBackground = -1;

    const changeHeroBackground = () => {
      const imageSources = Array.from(grid.querySelectorAll('img.product-image[src]'))
        .map((image) => image.currentSrc || image.src)
        .filter((source, index, sources) => source && sources.indexOf(source) === index);
      if (!imageSources.length) return;

      const candidates = imageSources.filter(
        (source) => heroBackgrounds[activeBackground]?.src !== source,
      );
      if (!candidates.length) return;
      const source = candidates[Math.floor(Math.random() * candidates.length)];
      const nextBackground = (activeBackground + 1) % heroBackgrounds.length;
      const image = heroBackgrounds[nextBackground];

      image.onload = () => {
        heroBackgrounds.forEach((background, index) => {
          background.classList.toggle('is-active', index === nextBackground);
        });
        activeBackground = nextBackground;
      };
      image.onerror = () => {
        image.classList.remove('is-active');
      };
      image.src = source;
    };

    changeHeroBackground();
    window.setInterval(changeHeroBackground, 10000);
  }

  if (grid && modal) {
    const modalImage = modal.querySelector('.product-modal-image');
    const modalVideo = modal.querySelector('.product-modal-video');
    const placeholder = modal.querySelector('.product-modal-placeholder');
    const previousButton = modal.querySelector('.product-modal-previous');
    const nextButton = modal.querySelector('.product-modal-next');
    const position = modal.querySelector('.product-modal-position');
    const status = modal.querySelector('.product-modal-status');
    let mediaItems = [];
    let activeIndex = 0;
    let requestId = 0;
    let activeProduct = null;

    const showMedia = (index) => {
      activeIndex = mediaItems.length ? (index + mediaItems.length) % mediaItems.length : 0;
      const media = mediaItems[activeIndex];
      modalVideo.pause();
      modalVideo.removeAttribute('src');
      modalVideo.load();
      if (media && media.type === 'video') {
        modalImage.hidden = true;
        modalVideo.hidden = false;
        modalVideo.src = media.src;
        modalVideo.muted = false;
        modalVideo.setAttribute('aria-label', `${modal.querySelector('#modal-product-name').textContent} video`);
        modalVideo.load();
        modalVideo.play()
          .then(() => {
            status.textContent = '';
          })
          .catch(() => {
            if (modal.open && !modalVideo.hidden) {
              status.textContent = 'Autoplay with sound was blocked. Press play on the video to hear audio.';
            }
          });
      } else if (media) {
        modalVideo.hidden = true;
        modalImage.hidden = false;
        modalImage.src = media.src;
        modalImage.alt = `${modal.querySelector('#modal-product-name').textContent} photo`;
      } else {
        modalVideo.hidden = true;
        modalImage.hidden = true;
      }
      placeholder.hidden = Boolean(media);
      const hasMultiple = mediaItems.length > 1;
      previousButton.hidden = !hasMultiple;
      nextButton.hidden = !hasMultiple;
      position.hidden = !hasMultiple;
      if (hasMultiple) position.textContent = `${activeIndex + 1} / ${mediaItems.length}`;
    };

    const showColorMedia = (colorName) => {
      const matchingImage = mediaItems.findIndex(
        (media) => media.type === 'image' && media.color === colorName,
      );
      const genericImage = mediaItems.findIndex(
        (media) => media.type === 'image' && !media.color,
      );
      showMedia(matchingImage >= 0 ? matchingImage : genericImage >= 0 ? genericImage : 0);
    };

    const syncSelectedSize = () => {
      if (!activeProduct) return;
      const sizeSelect = modal.querySelector('.product-modal-size');
      const colorSelect = modal.querySelector('#product-modal-color');
      const quantity = modal.querySelector('#product-modal-quantity');
      const submitButton = modal.querySelector('.product-modal-cart-form button[type="submit"]');
      const selectedSize = sizeSelect.value;
      const selectedColor = colorSelect.value;
      const colorPrompt = modal.querySelector('.product-modal-color-prompt');
      const colorRequired = activeProduct.colors.length > 0;
      const selectColorFirst = colorRequired && !selectedColor;
      colorPrompt.hidden = !selectColorFirst;
      sizeSelect.disabled = selectColorFirst;
      sizeSelect.title = selectColorFirst ? 'Please select a color first.' : '';
      modal.querySelector('.product-modal-sizes').title =
        selectColorFirst ? 'Please select a color first.' : '';
      const available = activeProduct.colors.length
        ? selectedColor
          ? Number(activeProduct.color_stock[selectedColor]?.[selectedSize] || 0)
          : selectedSize
            ? Number(activeProduct.size_stock[selectedSize] || 0)
            : activeProduct.stock
        : activeProduct.sizes.length
          ? Number(activeProduct.size_stock[selectedSize] || 0)
        : activeProduct.stock;
      quantity.max = String(available);
      if (Number(quantity.value) > available) quantity.value = String(available || 1);
      submitButton.disabled = available < 1
        || (activeProduct.colors.length > 0 && !selectedColor)
        || (activeProduct.sizes.length > 0 && !selectedSize);
      modal.querySelector('.product-modal-stock').textContent = activeProduct.colors.length
        ? (selectedColor && selectedSize
          ? `${available} in stock for ${selectedColor}, size ${selectedSize}`
          : selectedSize
            ? `Please select a color · ${available} in stock for size ${selectedSize}`
            : `Choose a color and size · ${activeProduct.stock} in stock`)
        : activeProduct.sizes.length
          ? (selectedSize
            ? `${available} in stock for size ${selectedSize}`
            : `${activeProduct.stock} in stock across all sizes`)
        : (available > 0 ? `${available} in stock` : 'Sold out');
    };

    const populateSizeOptions = () => {
      if (!activeProduct) return;
      const sizeSelect = modal.querySelector('.product-modal-size');
      const selectedColor = modal.querySelector('#product-modal-color').value;
      const previousSize = sizeSelect.value;
      const selectColorFirst = activeProduct.colors.length > 0 && !selectedColor;
      sizeSelect.replaceChildren();
      const chooseSize = document.createElement('option');
      chooseSize.value = '';
      chooseSize.textContent = selectColorFirst ? 'Select a color first' : 'Choose a size';
      sizeSelect.append(chooseSize);
      activeProduct.sizes.forEach((size) => {
        const option = document.createElement('option');
        option.value = size;
        const available = activeProduct.colors.length
          ? selectedColor
            ? Number(activeProduct.color_stock[selectedColor]?.[size] || 0)
            : Number(activeProduct.size_stock[size] || 0)
          : Number(activeProduct.size_stock[size] || 0);
        option.textContent = `${size} · ${available} in stock`;
        option.disabled = available < 1;
        sizeSelect.append(option);
      });
      if (previousSize && Array.from(sizeSelect.options).some(
        (option) => option.value === previousSize && !option.disabled,
      )) {
        sizeSelect.value = previousSize;
      }
      sizeSelect.disabled = selectColorFirst;
      sizeSelect.title = selectColorFirst ? 'Please select a color first.' : '';
    };

    const updateProduct = (product) => {
      activeProduct = product;
      modal.querySelector('#modal-product-name').textContent = product.name;
      modal.querySelector('.product-modal-category').textContent =
        `${product.category} · ${product.cloth_type}${product.occasion_category ? ` · ${product.occasion_category}` : ''}`;
      modal.querySelector('.product-modal-description p').textContent = product.description;
      const priceContainer = modal.querySelector('.product-modal-prices');
      priceContainer.replaceChildren();
      if (product.offer_price) {
        const oldPrice = document.createElement('del');
        oldPrice.textContent = product.price;
        const offerPrice = document.createElement('strong');
        offerPrice.textContent = product.offer_price;
        const discount = document.createElement('span');
        discount.className = 'sale-badge';
        discount.textContent = `${product.discount_percentage}% OFF`;
        priceContainer.append(oldPrice, offerPrice, discount);
      } else {
        const price = document.createElement('strong');
        price.textContent = product.price;
        priceContainer.append(price);
      }

      const sizesContainer = modal.querySelector('.product-modal-sizes');
      const sizeSelect = modal.querySelector('.product-modal-size');
      const colorsContainer = modal.querySelector('.product-modal-colors');
      const colorSelect = modal.querySelector('#product-modal-color');
      const colorSwatches = colorsContainer.querySelector('.product-color-swatches');
      colorSwatches.replaceChildren();
      const selectedColorName = colorsContainer.querySelector('.selected-color-name');
      selectedColorName.hidden = true;
      selectedColorName.querySelector('.selected-color-text').textContent = '';
      colorSelect.value = '';
      product.colors.forEach((color) => {
        const swatch = document.createElement('button');
        swatch.type = 'button';
        swatch.className = 'product-color-swatch';
        swatch.dataset.color = color.name;
        swatch.style.setProperty('--swatch', color.value);
        swatch.setAttribute('aria-label', `Select ${color.name} color`);
        swatch.setAttribute('aria-pressed', 'false');
        colorSwatches.append(swatch);
      });
      colorsContainer.hidden = product.colors.length === 0;
      colorSelect.required = product.colors.length > 0;
      sizesContainer.hidden = product.sizes.length === 0;
      sizeSelect.required = product.sizes.length > 0;
      populateSizeOptions();
      const quantity = modal.querySelector('#product-modal-quantity');
      quantity.value = '1';
      modal.querySelector('.product-modal-cart-form [name="product_id"]').value = product.id;
      modal.querySelector('.product-modal-cart-form button[type="submit"]').disabled = true;
      mediaItems = product.media;
      syncSelectedSize();
      showMedia(0);
    };

    const closeModal = () => {
      requestId += 1;
      modalVideo.pause();
      modalVideo.removeAttribute('src');
      modalVideo.load();
      modal.close();
    };

    grid.addEventListener('click', (event) => {
      const cardButton = event.target.closest('.product-card-link, .product-card-add');
      if (!cardButton) return;
      modal.showModal();
      document.body.classList.add('product-modal-open');
      const activeRequest = ++requestId;
      status.textContent = 'Loading product details…';
      modal.querySelector('#modal-product-name').textContent = '';
      modal.querySelector('.product-modal-category').textContent = '';
      modal.querySelector('.product-modal-stock').textContent = '';
      modal.querySelector('.product-modal-info-scroll .product-modal-description p').textContent = '';
      modal.querySelector('.product-modal-prices').replaceChildren();
      modal.querySelector('.product-modal-size').replaceChildren();
      modal.querySelector('#product-modal-color').value = '';
      modal.querySelector('.product-color-swatches').replaceChildren();
      modal.querySelector('.product-modal-sizes').hidden = true;
      modal.querySelector('.product-modal-colors').hidden = true;
      activeProduct = null;
      mediaItems = [];
      showMedia(0);
      fetch(cardButton.dataset.modalUrl)
        .then((response) => {
          if (!response.ok) throw new Error('Could not load product details.');
          return response.json();
        })
        .then((product) => {
          if (activeRequest !== requestId || !modal.open) return;
          status.textContent = '';
          updateProduct(product);
        })
        .catch(() => {
          if (activeRequest !== requestId || !modal.open) return;
          status.textContent = 'Product details could not be loaded. Please close and try again.';
        });
    });

    modal.querySelector('.product-modal-close').addEventListener('click', closeModal);
    const openFullImage = () => {
      if (!imageLightbox || modalImage.hidden) return;
      const image = imageLightbox.querySelector('.product-image-lightbox-photo');
      image.src = modalImage.src;
      image.alt = modalImage.alt;
      imageLightbox.showModal();
    };
    modalImage.addEventListener('click', openFullImage);
    modalImage.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openFullImage();
      }
    });
    if (imageLightbox) {
      const image = imageLightbox.querySelector('.product-image-lightbox-photo');
      const toggleImageZoom = () => {
        const zoomed = imageLightbox.classList.toggle('is-zoomed');
        image.setAttribute('aria-label', zoomed ? 'Fit product image to screen' : 'Zoom in on product image');
      };
      image.addEventListener('click', toggleImageZoom);
      image.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          toggleImageZoom();
        }
      });
      imageLightbox.querySelector('.product-image-lightbox-close').addEventListener('click', () => {
        imageLightbox.close();
      });
      imageLightbox.addEventListener('click', (event) => {
        if (event.target === imageLightbox) imageLightbox.close();
      });
      imageLightbox.addEventListener('close', () => {
        image.removeAttribute('src');
        imageLightbox.classList.remove('is-zoomed');
        image.setAttribute('aria-label', 'Zoom in on product image');
      });
    }
    modal.querySelector('.product-modal-size').addEventListener('change', syncSelectedSize);
    modal.querySelector('.product-color-swatches').addEventListener('click', (event) => {
      const swatch = event.target.closest('[data-color]');
      if (!swatch || !activeProduct) return;
      const colorName = swatch.dataset.color;
      modal.querySelector('#product-modal-color').value = colorName;
      modal.querySelectorAll('.product-color-swatch').forEach((button) => {
        const selected = button === swatch;
        button.setAttribute('aria-pressed', String(selected));
        button.classList.toggle('is-selected', selected);
      });
      const selectedColor = activeProduct.colors.find((color) => color.name === colorName);
      const selectedColorName = modal.querySelector('.product-modal-colors .selected-color-name');
      selectedColorName.querySelector('.selected-color-text').textContent = `Selected: ${colorName}`;
      selectedColorName.querySelector('.selected-color-indicator').style.setProperty('--swatch', selectedColor.value);
      selectedColorName.hidden = false;
      populateSizeOptions();
      syncSelectedSize();
      showColorMedia(colorName);
    });
    modal.querySelector('.product-modal-cart-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const submitButton = form.querySelector('button[type="submit"]');
      submitButton.disabled = true;
      try {
        const response = await fetch(form.dataset.addUrl, {
          method: 'POST',
          body: new FormData(form),
          headers: {'X-Requested-With': 'XMLHttpRequest'},
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not add the product to your cart.');
        document.querySelector('[data-cart-count]').textContent = result.cart_count;
        const notice = document.getElementById('storefront-notice');
        notice.replaceChildren();
        if (result.color) {
          const swatch = document.createElement('i');
          swatch.className = 'cart-color-swatch';
          swatch.style.setProperty('--swatch', result.color_code);
          swatch.setAttribute('aria-label', result.color);
          notice.append(swatch, document.createTextNode(' '));
        }
        notice.append(document.createTextNode(result.message));
        notice.hidden = false;
        closeModal();
      } catch (error) {
        status.textContent = error.message;
      } finally {
        syncSelectedSize();
      }
    });
    modal.addEventListener('close', () => {
      requestId += 1;
      document.body.classList.remove('product-modal-open');
      modalVideo.pause();
      modalVideo.removeAttribute('src');
      modalVideo.load();
    });
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModal();
    });
    modal.querySelectorAll('[data-modal-step]').forEach((button) => {
      button.addEventListener('click', () => {
        showMedia(activeIndex + Number(button.dataset.modalStep));
      });
    });
  }

  if (!grid || !loader || loader.dataset.hasMore !== '1') return;

  let offset = Number(loader.dataset.offset || 0);
  const batchSize = Number(loader.dataset.batchSize || 5);
  let loading = false;

  const loadMore = async () => {
    if (loading || loader.classList.contains('is-hidden')) return;
    loading = true;
    const params = new URLSearchParams(window.location.search);
    params.set('offset', offset);
    try {
      const response = await fetch(loader.dataset.moreUrl + '?' + params.toString());
      if (!response.ok) throw new Error('Could not load more products.');
      grid.insertAdjacentHTML('beforeend', await response.text());
      offset += batchSize;
      if (response.headers.get('X-Has-More') !== '1') loader.classList.add('is-hidden');
    } catch (_error) {
      loader.textContent = 'Scroll to try loading more products.';
    } finally {
      loading = false;
    }
  };

  new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) loadMore();
  }, { rootMargin: '300px' }).observe(loader);
})();