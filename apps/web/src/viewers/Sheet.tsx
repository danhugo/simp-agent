const MAX_ROWS = 1000;

/** csv/tsv text -> rows. Handles "quoted, fields" with "" escapes and newlines inside quotes. */
export function parse(text: string, sep: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"' && !cell) q = true;
    else if (c === sep) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

/** csv/tsv -> a table. */
export default function Sheet({ data, tsv }: { data: ArrayBuffer; tsv: boolean }) {
  const rows = parse(new TextDecoder().decode(data), tsv ? "\t" : ",");
  return (
    <div className="sheet-view">
      <table>
        <tbody>{rows.slice(0, MAX_ROWS).map((r, i) => <tr key={i}>{r.map((c, j) => i ? <td key={j}>{c}</td> : <th key={j}>{c}</th>)}</tr>)}</tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="muted small">Showing the first {MAX_ROWS} of {rows.length} rows. Download to see all.</p>}
    </div>
  );
}
