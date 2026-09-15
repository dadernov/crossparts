// Keep native document scrolling, replace only its gutter with a floating thumb.
(() => {
  const root = document.documentElement;
  const thumb = document.createElement('div');
  root.id ||= 'page-document';
  thumb.className = 'page-scroll-thumb';
  thumb.setAttribute('role', 'scrollbar');
  thumb.setAttribute('aria-label', 'Прокрутка страницы');
  thumb.setAttribute('aria-orientation', 'vertical');
  thumb.setAttribute('aria-controls', root.id);
  thumb.setAttribute('aria-valuemin', '0');
  thumb.tabIndex = 0;
  thumb.hidden = true;
  document.body.append(thumb);
  root.classList.add('overlay-scrollbar');
  let travel = 0;
  let maximum = 0;
  let frame = 0;
  let drag = null;
  function update() {
    frame = 0;
    const viewport = root.clientHeight;
    const height = document.scrollingElement.scrollHeight;
    maximum = Math.max(0, height - viewport);
    thumb.hidden = maximum <= 1;
    if (thumb.hidden) return;
    const size = Math.min(viewport - 8, Math.max(36, (viewport - 8) * viewport / height));
    travel = Math.max(0, viewport - 8 - size);
    thumb.style.height = `${size}px`;
    thumb.style.transform = `translateY(${4 + travel * Math.min(maximum, Math.max(0, scrollY)) / maximum}px)`;
    thumb.setAttribute('aria-valuemax', String(Math.round(maximum)));
    thumb.setAttribute('aria-valuenow', String(Math.round(Math.max(0, scrollY))));
  }
  function schedule() {
    if (!frame) frame = requestAnimationFrame(update);
  }
  addEventListener('scroll', schedule, {passive: true});
  addEventListener('resize', schedule, {passive: true});
  new ResizeObserver(schedule).observe(document.body);
  thumb.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    drag = {y: event.clientY, scroll: scrollY};
    thumb.setPointerCapture(event.pointerId);
  });
  thumb.addEventListener('pointermove', event => {
    if (!drag || !travel) return;
    scrollTo({top: drag.scroll + (event.clientY - drag.y) * maximum / travel, behavior: 'instant'});
  });
  const stop = () => { drag = null; };
  thumb.addEventListener('pointerup', stop);
  thumb.addEventListener('pointercancel', stop);
  thumb.addEventListener('lostpointercapture', stop);
  thumb.addEventListener('keydown', event => {
    let top;
    switch (event.key) {
      case 'ArrowDown': top = scrollY + 40; break;
      case 'ArrowUp': top = scrollY - 40; break;
      case 'PageDown': top = scrollY + root.clientHeight * .9; break;
      case 'PageUp': top = scrollY - root.clientHeight * .9; break;
      case 'Home': top = 0; break;
      case 'End': top = maximum; break;
      default: return;
    }
    event.preventDefault();
    scrollTo({top, behavior: 'instant'});
  });
  update();
})();
