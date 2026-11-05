// Tailscale HTTP is encrypted by the VPN, but browsers do not classify its IP
// as a secure context. Keep request IDs and copy buttons usable there as well.
export function requestId(crypto = globalThis.crypto) {
  if (crypto.randomUUID) return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(value); return; } catch { /* Try the user-gesture fallback. */ }
  }
  const previous = document.activeElement;
  const input = document.createElement('textarea');
  input.value = value; input.readOnly = true;
  input.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
  document.body.append(input); input.select();
  try { if (!document.execCommand('copy')) throw new Error('Copy is unavailable in this browser.'); }
  finally { input.remove(); previous?.focus(); }
}
