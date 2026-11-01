(() => {
  const gallery = document.querySelector('[data-product-gallery]');
  const lightbox = document.querySelector('.product-image-lightbox');
  if (!gallery) return;

  const mainImage = gallery.querySelector('#detail-main-image');
  const video = gallery.querySelector('#detail-main-video');
  const mediaItems = Array.from(gallery.querySelectorAll('.detail-gallery-items [data-media-src]'));
  const arrows = gallery.querySelectorAll('[data-gallery-step]');
  const position = gallery.querySelector('.detail-gallery-position');
  let activeIndex = 0;
  const preloadCache = new Map();

  const preloadMedia = () => {
    mediaItems.forEach((media) => {
      const src = media.dataset.mediaSrc;
      if (!src || preloadCache.has(src)) return;
      if (media.dataset.mediaType === 'video') {
        const preloadVideo = document.createElement('video');
        preloadVideo.preload = 'metadata';
        preloadVideo.muted = true;
        preloadVideo.src = src;
        preloadVideo.load();
        preloadCache.set(src, preloadVideo);
      } else {
        const preloadImage = new Image();
        preloadImage.decoding = 'async';
        preloadImage.src = src;
        preloadCache.set(src, preloadImage);
      }
    });
  };

  const showMedia = (index) => {
    if (!mediaItems.length) return;
    activeIndex = (index + mediaItems.length) % mediaItems.length;
    const media = mediaItems[activeIndex];
    video.pause();
    if (media.dataset.mediaType === 'video') {
      mainImage.hidden = true;
      video.hidden = false;
      video.src = media.dataset.mediaSrc;
      video.setAttribute('aria-label', media.dataset.mediaAlt || 'Product video');
      video.load();
    } else {
      video.hidden = true;
      video.removeAttribute('src');
      video.load();
      mainImage.hidden = false;
      mainImage.src = media.dataset.mediaSrc;
      mainImage.alt = media.dataset.mediaAlt || 'Product photo';
    }
    if (position) position.textContent = `${activeIndex + 1} / ${mediaItems.length}`;
  };

  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(preloadMedia, { timeout: 1500 });
  } else {
    window.setTimeout(preloadMedia, 100);
  }

  arrows.forEach((arrow) => {
    arrow.addEventListener('click', () => showMedia(activeIndex + Number(arrow.dataset.galleryStep)));
  });

  const colorButtons = Array.from(gallery.querySelectorAll('[data-detail-color]'));
  const showColor = (colorName) => {
    colorButtons.forEach((button) => {
      const selected = button.dataset.detailColor === colorName;
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    const selectedName = gallery.querySelector('[data-detail-color-name]');
    if (selectedName) selectedName.textContent = `Color: ${colorName}`;
    gallery.querySelectorAll('[data-color-inventory]').forEach((inventory) => {
      inventory.hidden = inventory.dataset.colorInventory !== colorName;
    });
    const specific = mediaItems.findIndex(
      (media) => media.dataset.mediaType === 'image' && media.dataset.mediaColor === colorName,
    );
    const generic = mediaItems.findIndex(
      (media) => media.dataset.mediaType === 'image' && !media.dataset.mediaColor,
    );
    if (specific >= 0 || generic >= 0) showMedia(specific >= 0 ? specific : generic);
  };
  colorButtons.forEach((button) => {
    button.addEventListener('click', () => showColor(button.dataset.detailColor));
  });
  if (colorButtons.length) showColor(colorButtons[0].dataset.detailColor);

  if (mainImage && lightbox) {
    const lightboxImage = lightbox.querySelector('.product-image-lightbox-photo');
    const openLightbox = () => {
      if (mainImage.hidden || !mainImage.src) return;
      lightboxImage.src = mainImage.src;
      lightboxImage.alt = mainImage.alt;
      lightbox.showModal();
    };
    const toggleZoom = () => {
      const zoomed = lightbox.classList.toggle('is-zoomed');
      lightboxImage.setAttribute('aria-label', zoomed ? 'Fit product image to screen' : 'Zoom in on product image');
    };
    mainImage.addEventListener('click', openLightbox);
    mainImage.style.cursor = 'zoom-in';
    lightboxImage.addEventListener('click', toggleZoom);
    lightboxImage.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleZoom();
      }
    });
    lightbox.querySelector('.product-image-lightbox-close').addEventListener('click', () => lightbox.close());
    lightbox.addEventListener('click', (event) => {
      if (event.target === lightbox) lightbox.close();
    });
    lightbox.addEventListener('close', () => {
      lightboxImage.removeAttribute('src');
      lightbox.classList.remove('is-zoomed');
      lightboxImage.setAttribute('aria-label', 'Zoom in on product image');
    });
  }
})();
