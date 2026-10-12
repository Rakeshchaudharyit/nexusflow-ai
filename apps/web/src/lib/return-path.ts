export const PATH_HEADER = "x-nexusflow-path";

/** Only same-origin workspace paths are honoured, so `next` cannot redirect off-site. */
export function returnPath(value: string | null | undefined): string {
  if (!value || !/^\/app(?:[/?#]|$)/.test(value) || /[\\\s]/.test(value))
    return "/app";
  return value;
}

export const loginURL = (path: string | null | undefined) => {
  const target = returnPath(path);
  return target === "/app"
    ? "/login"
    : `/login?next=${encodeURIComponent(target)}`;
};
