/**
 * App-facing identity shape — provider-agnostic.
 * Product code (Saved Reports later) should only depend on `id`, not Supabase types.
 */
export type AuthUser = {
  id: string;
  email: string | null;
};
