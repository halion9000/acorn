/** A yearly cost for display: "$1,200", "$1,200.50", "$0"; whole dollars drop the cents (pure). */
export function dollars(amount: number): string {
  return `$${amount.toLocaleString('en-US', { minimumFractionDigits: Number.isInteger(amount) ? 0 : 2, maximumFractionDigits: 2 })}`;
}
