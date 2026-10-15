/**
 * Return a same-origin application path, rejecting absolute and protocol-relative URLs.
 * Keeping this small and dependency-free lets the redirect policy be tested by Node.
 * @param {unknown} value
 * @returns {string | null}
 */
export function safeRedirectPath(value) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return null;
  }
  if ([...value].some((character) => character.charCodeAt(0) < 0x20 || character.charCodeAt(0) === 0x7f)) {
    return null;
  }

  try {
    const parsed = new URL(value, "https://siraloom.invalid");
    if (parsed.origin !== "https://siraloom.invalid") return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}
