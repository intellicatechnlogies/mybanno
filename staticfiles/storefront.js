(() => {
  const grid = document.getElementById('product-grid');
  const loader = document.getElementById('product-loader');
  const modal = document.getElementById('product-modal');
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

    const updateProduct = (product) => {
      modal.querySelector('#modal-product-name').textContent = product.name;
      modal.querySelector('.product-modal-category').textContent =
        `${product.category} · ${product.cloth_type}`;
      modal.querySelector('.product-modal-stock').textContent =
        product.stock > 0 ? `${product.stock} in stock` : 'Sold out';
      modal.querySelector('.product-modal-description p').textContent = product.description;
      const priceContainer = modal.querySelector('.product-modal-prices');
      priceContainer.replaceChildren();
      if (product.offer_price) {
        const oldPrice = document.createElement('del');
        oldPrice.textContent = product.price;
        const offerPrice = document.createElement('strong');
        offerPrice.textContent = product.offer_price;
        priceContainer.append(oldPrice, offerPrice);
      } else {
        const price = document.createElement('strong');
        price.textContent = product.price;
        priceContainer.append(price);
      }

      const sizesContainer = modal.querySelector('.product-modal-sizes');
      const sizeSelect = modal.querySelector('.product-modal-size');
      sizeSelect.replaceChildren();
      const chooseSize = document.createElement('option');
      chooseSize.value = '';
      chooseSize.textContent = 'Choose a size';
      sizeSelect.append(chooseSize);
      product.sizes.forEach((size) => {
        const option = document.createElement('option');
        option.value = size;
        option.textContent = size;
        sizeSelect.append(option);
      });
      sizesContainer.hidden = product.sizes.length === 0;
      sizeSelect.required = product.sizes.length > 0;
      const quantity = modal.querySelector('#product-modal-quantity');
      quantity.max = String(product.stock);
      quantity.value = '1';
      modal.querySelector('.product-modal-cart-form [name="product_id"]').value = product.id;
      modal.querySelector('.product-modal-cart-form button[type="submit"]').disabled = product.stock < 1;
      mediaItems = product.media;
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
      const activeRequest = ++requestId;
      status.textContent = 'Loading product details…';
      modal.querySelector('#modal-product-name').textContent = '';
      modal.querySelector('.product-modal-category').textContent = '';
      modal.querySelector('.product-modal-stock').textContent = '';
      modal.querySelector('.product-modal-description p').textContent = '';
      modal.querySelector('.product-modal-prices').replaceChildren();
      modal.querySelector('.product-modal-size').replaceChildren();
      modal.querySelector('.product-modal-sizes').hidden = true;
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
        notice.textContent = result.message;
        notice.hidden = false;
        closeModal();
      } catch (error) {
        status.textContent = error.message;
      } finally {
        submitButton.disabled = Number(modal.querySelector('#product-modal-quantity').max) < 1;
      }
    });
    modal.addEventListener('close', () => {
      requestId += 1;
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