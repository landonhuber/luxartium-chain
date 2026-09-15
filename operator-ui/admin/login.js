document.querySelector('#login').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button');
  const input = document.querySelector('#key');
  const error = document.querySelector('#error');
  button.disabled = true;
  error.textContent = '';
  try {
    const response = await fetch('/session', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key:input.value}), signal:AbortSignal.timeout(10000)});
    input.value = '';
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    // Preserve only the two supported legacy operator bookmarks, never a supplied URL.
    const hash = ['#/roadmap', '#/processes'].includes(location.hash) ? location.hash : '';
    location.replace('/admin/' + hash);
  } catch (failure) {
    error.textContent = failure.name === 'TimeoutError' ? 'Sign-in timed out. Try again.' : failure.message;
  } finally { input.value = ''; button.disabled = false; }
});
