const options = document.querySelector('#entry-options');
const login = document.querySelector('#entry-login');
const openLogin = document.querySelector('#open-login');
// Follow /login normally so password managers see a visible form at document load.
// The server renders the same two-column page with the right panel switched to login.
document.querySelector('#back-to-options').addEventListener('click', event => {
  event.preventDefault();
  login.hidden = true;
  options.hidden = false;
  openLogin.focus({preventScroll: true});
});
document.querySelector('#show-password').addEventListener('click', event => {
  const password = document.querySelector('#password');
  const show = password.type === 'password';
  password.type = show ? 'text' : 'password';
  event.currentTarget.setAttribute('aria-pressed', String(show));
  event.currentTarget.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
});
// Native POST /login and its redirect signal successful authentication to the browser.
