import { read, utils } from "xlsx";

const MAX_ROWS = 1000;

/** csv/tsv/xlsx -> a table of the first sheet. */
export default function Sheet({ data, csv }: { data: ArrayBuffer; csv: boolean }) {
  // ponytail: first sheet only, add sheet tabs when someone needs the others
  const wb = csv ? read(new TextDecoder().decode(data), { type: "string" }) : read(data, { type: "array" });
  const rows = utils.sheet_to_json<unknown[]>(wb.Sheets[wb.SheetNames[0]], { header: 1, defval: "" });
  return (
    <div className="sheet-view">
      <table>
        <tbody>{rows.slice(0, MAX_ROWS).map((r, i) => <tr key={i}>{r.map((c, j) => i ? <td key={j}>{String(c)}</td> : <th key={j}>{String(c)}</th>)}</tr>)}</tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="muted small">Showing the first {MAX_ROWS} of {rows.length} rows. Download to see all.</p>}
    </div>
  );
}
