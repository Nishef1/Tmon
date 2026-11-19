/** One word for how far the past evidence can be trusted (t is the statistical strength). */
export function trustWord(t: number | null | undefined): string | null {
  if (t == null) return null;
  return t >= 3 ? "زیاد" : t >= 2 ? "متوسط" : "کم";
}
