/**
 * Extract a displayable initial letter from a name, handling unicode math bold,
 * italic, emoji, and other non-BMP characters that render as "�" when sliced.
 *
 * Examples:
 *   "𝑲𝑯𝟕𝟎𝟔" → "K"
 *   "Oybek"  → "O"
 *   "🔥Fire" → "F"
 *   ""       → fallback
 */
export function getInitial(name: string | null | undefined, fallback = "?"): string {
  if (!name) return fallback;

  // Normalize unicode: NFKD decomposes math bold 𝑲→K, etc.
  const normalized = name.normalize("NFKD");

  // Find first letter (Latin or Cyrillic) in the normalized string
  for (const char of normalized) {
    // Latin A-Z a-z
    if ((char >= "A" && char <= "Z") || (char >= "a" && char <= "z")) {
      return char.toUpperCase();
    }
    // Cyrillic А-я (U+0410-U+044F) + Ё/ё
    const code = char.charCodeAt(0);
    if ((code >= 0x0410 && code <= 0x044f) || code === 0x0401 || code === 0x0451) {
      return char.toUpperCase();
    }
  }

  // If no letter found, try first visible character from original string
  for (const char of name) {
    if (char.trim()) return char;
  }

  return fallback;
}

/**
 * Format a number with dot separators: 15200000 → "15.200.000"
 */
export function formatPrice(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "\u2014";
  const n = typeof val === "string" ? Number(val) : val;
  if (isNaN(n)) return "\u2014";
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/**
 * Russian plural: picks the right form based on count.
 *   plural(1, "товар", "товара", "товаров") → "товар"
 *   plural(2, "товар", "товара", "товаров") → "товара"
 *   plural(5, "товар", "товара", "товаров") → "товаров"
 */
export function plural(n: number, one: string, few: string, many: string): string {
  const abs = Math.abs(n) % 100;
  const lastDigit = abs % 10;
  if (abs >= 11 && abs <= 19) return many;
  if (lastDigit === 1) return one;
  if (lastDigit >= 2 && lastDigit <= 4) return few;
  return many;
}
