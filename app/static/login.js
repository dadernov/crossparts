document.querySelector('#show-password').addEventListener('change', (event) => {
  document.querySelector('#password').type = event.target.checked ? 'text' : 'password';
});
