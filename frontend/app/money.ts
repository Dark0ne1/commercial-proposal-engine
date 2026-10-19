export function formatMoney(value: string): string {
  const [whole, fraction = ""] = value.split(".");
  return `${new Intl.NumberFormat("ru-RU").format(BigInt(whole))},${fraction.padEnd(2, "0")} ₽`;
}
