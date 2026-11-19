'use client';

/**
 * A month chosen with two dropdowns, a Month and a Year, instead of one long list of "October 2026", "September 2026" and so on. With years of history the long list is slow to scan; here the Year
 * lists only the years that have data and the Month lists only the months of that year that do. Changing the year keeps the same month when that year has it, else the newest month it has.
 */

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/** The years that have data, newest first (pure). */
export function yearsOf(months: string[]): string[] {
  return [...new Set(months.map((m) => m.slice(0, 4)))].sort().reverse();
}

/** The months of one year that have data, January first (pure). */
export function monthsOfYear(months: string[], year: string): string[] {
  return months.filter((m) => m.startsWith(`${year}-`)).sort();
}

/** The month to show after the year changes: the same month of the new year when it has data, else the newest month that year has (pure). */
export function monthForYear(months: string[], current: string, year: string): string {
  const inYear = monthsOfYear(months, year);
  const same = `${year}-${current.slice(5, 7)}`;
  return inYear.includes(same) ? same : (inYear[inYear.length - 1] ?? current);
}

export function monthName(month: string): string {
  return MONTH_NAMES[Number(month.slice(5, 7)) - 1] ?? month;
}

export function MonthYearPicker({ months, value, onChange, className }: { months: string[]; value: string; onChange: (month: string) => void; className?: string }) {
  const year = value.slice(0, 4);
  return (
    <span className="inline-flex items-center gap-2">
      <select aria-label="Month" className={className} value={value} onChange={(e) => onChange(e.target.value)}>
        {monthsOfYear(months, year).map((m) => (
          <option key={m} value={m}>
            {monthName(m)}
          </option>
        ))}
      </select>
      <select aria-label="Year" className={className} value={year} onChange={(e) => onChange(monthForYear(months, value, e.target.value))}>
        {yearsOf(months).map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
    </span>
  );
}

export default MonthYearPicker;
