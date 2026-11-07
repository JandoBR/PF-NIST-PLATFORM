// Las columnas DATETIME de SQLite llegan como "YYYY-MM-DD HH:MM:SS" (o ISO) sin zona: son UTC,
// pero `new Date()` las interpretaría como hora local. Las cadenas que ya traen `Z` u offset se
// respetan tal cual.

const ZONE_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/** Convierte una fecha de la base de datos a `Date`, asumiendo UTC cuando no declara zona. */
export function parseDbDate(value: string): Date {
  const normalized = value.trim().replace(' ', 'T');
  const hasTime = normalized.includes('T');
  const hasZone = ZONE_SUFFIX.test(normalized);
  return new Date(hasTime && !hasZone ? `${normalized}Z` : normalized);
}

/** Formatea una fecha de la base de datos; devuelve '' si no es válida. */
export function formatDbDate(
  value: string,
  locale = 'es',
  options?: Intl.DateTimeFormatOptions
): string {
  const date = parseDbDate(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(locale, options);
}
