export async function request(path, body, options = {}) {
  const form = body instanceof FormData;
  const response = await fetch(`/api/studio${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: form || body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
    ...options,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
