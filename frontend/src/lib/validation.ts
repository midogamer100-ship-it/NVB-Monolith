/**
 * Client-side checks that mirror the server rules in docs/ACCOUNTS_AND_CASH.md.
 * They only improve feedback; the server re-validates everything.
 */

export const CITIES = [
  "Cairo",
  "Giza",
  "Alexandria",
  "Mansoura",
  "Tanta",
  "Aswan",
  "Luxor",
  "Ismailia",
  "Port Said",
  "Suez",
  "Hurghada",
  "Zagazig",
] as const;

export const USERNAME_RE = /^[a-z][a-z0-9_.-]{3,31}$/;
export const EMAIL_RE = /^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$/;
export const PHONE_RE = /^\+20(10|11|12|15)\d{8}$/;
export const FULL_NAME_RE = /^[\p{L}][\p{L} '-]{1,118}[\p{L}]$/u;

export function normalizeUsername(v: string): string {
  return v.trim().toLowerCase();
}

export function normalizePhone(v: string): string {
  return v.replace(/[\s-]/g, "");
}

export interface PasswordRule {
  id: string;
  label: string;
  ok: boolean;
}

export function passwordRules(password: string, username: string): PasswordRule[] {
  const u = normalizeUsername(username);
  return [
    { id: "length", label: "10 to 128 characters", ok: password.length >= 10 && password.length <= 128 },
    { id: "letter", label: "At least one letter", ok: /\p{L}/u.test(password) },
    { id: "digit", label: "At least one number", ok: /\d/.test(password) },
    { id: "username", label: "Does not contain the username", ok: !u || !password.toLowerCase().includes(u) },
  ];
}

export function passwordOk(password: string, username: string): boolean {
  return passwordRules(password, username).every((r) => r.ok);
}

export interface PersonFields {
  username: string;
  full_name: string;
  email: string;
  phone: string;
  city: string;
}

/** Field errors for the shared sign-up / admin-create fields. Empty object = valid. */
export function validatePerson(f: PersonFields): Partial<Record<keyof PersonFields, string>> {
  const errs: Partial<Record<keyof PersonFields, string>> = {};
  const name = f.full_name.trim();
  if (name.length < 3 || name.length > 120 || !FULL_NAME_RE.test(name)) {
    errs.full_name = "Enter your full name (3–120 letters; spaces, apostrophes and hyphens allowed).";
  }
  if (!USERNAME_RE.test(normalizeUsername(f.username))) {
    errs.username = "4–32 characters: start with a letter, then letters, numbers, dot, dash or underscore.";
  }
  if (!EMAIL_RE.test(f.email.trim())) errs.email = "Enter a valid email address.";
  if (!PHONE_RE.test(normalizePhone(f.phone))) errs.phone = "Enter an Egyptian mobile number like +201012345678.";
  if (!(CITIES as readonly string[]).includes(f.city)) errs.city = "Choose a city.";
  return errs;
}
