document.querySelectorAll('form[action="/trial"]').forEach((form) => {
  form.addEventListener('submit', () => {
    window.open('https://t.me/mrbdigital', '_blank', 'noopener,noreferrer');
  });
});

