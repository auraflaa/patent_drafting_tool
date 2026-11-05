// Role helpers. Firestore stores `role_codes` as an unordered array, so any UI
// that picks "the" role (home path, dashboard shell, notification links) has to
// apply a fixed priority instead of reading index 0.

import { ALL_ROLE_CODES, ROLE_HOME, type RoleCode } from "./types";

/** Most privileged first. A user with two roles sees the stronger workspace. */
const ROLE_PRIORITY: readonly RoleCode[] = ALL_ROLE_CODES;

export function primaryRole(
  roles: readonly string[] | null | undefined,
): RoleCode | null {
  for (const role of ROLE_PRIORITY) {
    if (roles?.includes(role)) return role;
  }
  return null;
}

/** Dashboard root for a user, or the login page when they hold no known role. */
export function homePathFor(roles: readonly string[] | null | undefined): string {
  const role = primaryRole(roles);
  return role ? ROLE_HOME[role] : "/login";
}

/**
 * Deep link to a patent. Agents draft, admins administer, innovators own;
 * Super Admin reuses the admin pages.
 */
export function patentPathFor(
  roles: readonly string[] | null | undefined,
  patentId: string,
): string {
  switch (primaryRole(roles)) {
    case "PATENT_AGENT":
      return `/agent/patents/${patentId}/draft`;
    case "ADMIN":
    case "SUPER_ADMIN":
      return `/admin/patents/${patentId}`;
    case "INNOVATOR":
      return `/innovator/patents/${patentId}`;
    default:
      return "/login";
  }
}
