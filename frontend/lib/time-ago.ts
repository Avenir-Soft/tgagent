/** Returns a human-readable relative time string in Russian. */
export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = now - then;
  if (diff < 0) return "только что";

  const sec = Math.floor(diff / 1000);
  if (sec < 60) return "только что";

  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} мин назад`;

  const hrs = Math.floor(min / 60);
  if (hrs < 24) return `${hrs} ч назад`;

  const days = Math.floor(hrs / 24);
  if (days === 1) return "вчера";
  if (days < 7) return `${days} дн назад`;

  const weeks = Math.floor(days / 7);
  if (weeks < 4) return `${weeks} нед назад`;

  return new Date(dateStr).toLocaleDateString("ru", { day: "numeric", month: "short" });
}
