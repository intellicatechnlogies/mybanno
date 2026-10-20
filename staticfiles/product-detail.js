(() => {
  const gallery = document.querySelector('[data-product-gallery]');
  if (!gallery) return;

  const image = gallery.querySelector('#detail-main-image');
  const video = gallery.querySelector('#detail-main-video');
  const mediaItems = Array.from(gallery.querySelectorAll('.detail-gallery-items [data-media-src]'));
  const arrows = gallery.querySelectorAll('[data-gallery-step]');
  const position = gallery.querySelector('.detail-gallery-position');
  if (!image || !video || mediaItems.length < 2 || arrows.length === 0 || !position) return;

  let activeIndex = 0;
  arrows.forEach((arrow) => {
    arrow.addEventListener('click', () => {
      activeIndex = (activeIndex + Number(arrow.dataset.galleryStep) + mediaItems.length) % mediaItems.length;
      const media = mediaItems[activeIndex];
      video.pause();
      if (media.dataset.mediaType === 'video') {
        image.hidden = true;
        video.hidden = false;
        video.src = media.dataset.mediaSrc;
        video.setAttribute('aria-label', media.dataset.mediaAlt || 'Product video');
        video.load();
      } else {
        video.hidden = true;
        video.removeAttribute('src');
        video.load();
        image.hidden = false;
        image.src = media.dataset.mediaSrc;
        image.alt = media.dataset.mediaAlt || 'Product photo';
      }
      position.textContent = `${activeIndex + 1} / ${mediaItems.length}`;
    });
  });
})();
