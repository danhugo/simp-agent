import { describe, expect, it } from "vitest";
import { fileRef } from "./Chat";

describe("fileRef", () => {
  it("takes workspace file names", () => {
    expect(fileRef("report.docx")).toBe("report.docx");
    expect(fileRef("/work/site/index.html")).toBe("site/index.html");
    expect(fileRef("Xem-truoc-Chien-luoc-F&B.html")).toBe("Xem-truoc-Chien-luoc-F&B.html");
    expect(fileRef("Báo cáo tháng 11.xlsx")).toBe("Báo cáo tháng 11.xlsx");
  });
  it("skips things that are not workspace files", () => {
    for (const t of ["npm install", "/etc/passwd", "https://x.com/a.js", "../secret.txt", "a\nb.txt", "x = 1.5", "README", "/tmp/a.txt", "os.path", "np.array", "self.name"])
      expect(fileRef(t)).toBeUndefined();
  });
});
