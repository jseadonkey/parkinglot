/** Set via next.config env so client fetches hit /api under basePath (operator console). */
export function publicBasePath(): string {
  return process.env.NEXT_PUBLIC_BASE_PATH ?? "";
}
