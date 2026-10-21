/** JSON request adapter for the shared collection filter. Throws on invalid input. */
export function filterRequest<T extends Record<string, unknown>>(request: {
  items: readonly T[];
  query?: string;
  text_fields?: readonly string[];
  facets?: Record<string, string | number | boolean | null>;
}): T[];
