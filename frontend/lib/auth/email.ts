/** Light email check — allows dots in the local part (e.g. first.last@gmail.com). */
export function isValidEmail(value: string): boolean {
  const email = value.trim();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
