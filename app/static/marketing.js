for (const button of document.querySelectorAll('[data-copy]')) {
  button.addEventListener('click', async () => {
    const number = button.dataset.copy;
    const status = document.querySelector('.copy-status');
    try {
      await navigator.clipboard.writeText(number);
      if (status) status.textContent = `${number} скопирован`;
      button.classList.add('copied');
      setTimeout(() => button.classList.remove('copied'), 1500);
    } catch (_) {
      const range = document.createRange();
      range.selectNodeContents(button.firstChild);
      const selection = getSelection();
      selection.removeAllRanges(); selection.addRange(range);
      if (status) status.textContent = 'Номер выделен — скопируйте его через меню браузера.';
    }
  });
}
