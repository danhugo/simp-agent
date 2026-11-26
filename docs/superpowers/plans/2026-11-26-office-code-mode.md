# Office code mode (`office_run`)

**Mục tiêu:** agent làm việc với .pptx/.docx/.xlsx bằng cách viết **một script Python** gọi API `office` (bọc officecli), chạy trong **một lần gọi tool**, thay vì gọi bash/tool nhiều lần hoặc viết JSON batch thủ công.

**Ý tưởng gốc:** Cloudflare Code Mode: API có kiểu + một tool chạy code + chỉ trả kết quả cuối; tra cứu API theo nhu cầu (search/describe) thay vì nạp hết vào context.

**Phạm vi:** officecli v1.0.162 (`toolset.OFFICECLI`). Chạy trong sandbox của agent (E2B ở prod, Docker ở local).

---

## 1. Kiến trúc

```
model ──office_run(code)──▶ Office plugin (host)
                              │ ghi /tmp/office-run-XXXX/main.py (prelude + code)
                              │ ctx.env.exec("python main.py", timeout)
                              ▼
                       sandbox: python + module `office` (/opt/simp/py/office.py)
                              │ subprocess list-args → officecli … --json
                              │ ghi sidecar: touched.json, images.json
                              ▼
                   plugin đọc sidecar → close + validate + issues cho file bị sửa
                                     → load ảnh vào ctx.images
                   ◀── trả: stdout (cắt) + traceback + kiểm tra + "[N ảnh]"
```

- Module `office` là **một file Python thuần stdlib** (~200 dòng), không phụ thuộc gì → chạy được ở mọi sandbox có Python.
- Prelude tự `import office` và đăng ký `atexit` để flush + close mọi file đã mở.

## 2. API của module `office`

### 2.1 Mở / tạo
| API | officecli |
|---|---|
| `d = office.open(path)` | `open` (resident) |
| `d = office.create(path, force=False)` | `close`→`rm`→`create`→`open` (idiom an toàn trong help) |
| `d.save()` / `d.close()` | `save` / `close` (tự gọi ở cuối script) |

### 2.2 Đọc (trả object Python từ `--json`; tự flush hàng đợi trước)
| API | officecli |
|---|---|
| `d.get(path="/")` → `Node` | `get --json` |
| `d.query(selector)` → `list[Node]` | `query --json` |
| `d.view(mode, **opts)` → str | `view` mode `text, annotated, outline, stats, issues, html, forms` (+ `start,end,max_lines,type,limit,cols,range`) |
| `d.raw(part="/document")` → str | `raw` |
| `d.dump(path="/")` → list[dict] | `dump` (batch script tái phát được) |
| `d.validate()` / `d.issues(type=None)` | `validate` / `view issues` |
| `d.stats()` | `view stats` |

`Node` có `.path`, `.type`, `.text`, `.props` (dict), `.children`, và tiện ích `.set(**props)`, `.remove()`.

### 2.3 Sửa (vào **hàng đợi**, gửi 1 `batch` khi cần đọc / save / close / kết thúc)
| API | officecli |
|---|---|
| `d.add(parent, type, before=None, after=None, **props)` | `add` |
| `d.set(path, **props)` | `set` |
| `d.remove(path)` | `remove` |
| `d.move(path, to=None, before=None, after=None)` | `move` |
| `d.swap(path1, path2)` | `swap` |
| `d.flush()` | gửi hàng đợi ngay |

- Props: Python value → chuỗi officecli (`True`→`"true"`, số giữ nguyên, `"1cm"` giữ nguyên). Text có `\n` (đoạn mới) / `\v` (xuống dòng) đúng quy ước officecli.
- Mỗi lệnh xếp hàng ghi lại **số dòng trong script của model** → khi batch lỗi ở item k, báo `main.py:23 d.set(...): <lỗi officecli>`.
- `add` cần id/path của phần tử mới (để dùng ngay) → `add` trả `Pending`; truy cập `.path` sẽ tự flush và lấy path thật từ kết quả batch.

### 2.4 Cấp thấp / đặc thù
| API | officecli |
|---|---|
| `d.raw_set(part, xml)` | `raw-set` (flush trước) |
| `d.add_part(parent)` → rId | `add-part` |
| `d.refresh()` | `refresh` (docx cần Word+Windows → trả cảnh báo rõ ràng trên Linux) |
| `d.import_csv(parent, csv_path)` | `import` (xlsx) |
| `office.merge(template, out, data: dict)` | `merge` |
| `office.replay(path, ops)` | `batch` với list dict sẵn có (vd. từ `dump`) |

### 2.5 Xem bằng mắt
| API | officecli |
|---|---|
| `d.screenshot(page=1, grid=None, range=None, width=1600, height=1200)` → path PNG | `view screenshot -o …` |
| `d.pdf(out)` / `d.html(out)` / `d.svg(out)` | `view pdf/html/svg -o …` |

`screenshot()` ghi path vào `images.json` → plugin nạp ảnh cho model (nếu model có vision; tối đa 4 ảnh/lần chạy, `shrink_image`).

### 2.6 Tra cứu API (kiểu search/describe)
| API | officecli |
|---|---|
| `office.help(fmt)` | `help <fmt>`: liệt kê element |
| `office.help(fmt, element, verb=None)` | `help <fmt> [verb] <element>`: thuộc tính chi tiết |
| `office.search(fmt, word)` | `help all --jsonl` lọc theo chữ (element/property) |

### 2.7 Lối thoát
`office.cli(*args, json=True)`: chạy officecli bất kỳ (list args, không escape), cho lệnh mới/chưa bọc.

### 2.8 Không đưa vào (có lý do)
| officecli | Lý do |
|---|---|
| `watch`, `unwatch` | server preview trực tiếp; trong sandbox không ai xem. Thay bằng `screenshot()`. |
| `mcp`, `skills`, `install`, `plugins` | cài đặt/tích hợp, không phải thao tác file. Vẫn gọi được qua `office.cli` nếu thật cần. |

→ Mọi lệnh thao tác file của officecli đều có API (bảng trên) hoặc qua `office.cli`.

## 3. Tool `office_run`

```
office_run(code: str, timeout: int = 120)
```
Mô tả tool (~400 token): mẫu dùng, danh sách hàm ở mục 2 (một dòng mỗi hàm), quy tắc: "tra thuộc tính bằng office.help trước khi đoán", "đường dẫn phần tử lấy từ d.view('annotated') hoặc d.query".

Kết quả trả về:
1. stdout (cắt `OUT_MAX`), stderr/traceback (chỉ dòng trong `main.py` + dòng cuối).
2. Với mỗi file bị sửa: `validate` + `issues` (lọc house-style như `explain()` hiện có).
3. `[Pictures: …]` nếu có screenshot.

An toàn: chạy bằng cùng quyền như bash hiện tại (không mở quyền mới); timeout; giới hạn output; script nằm trong thư mục tạm, xóa sau khi chạy.

## 4. Tool cũ
- **Bỏ `office_edit`** (JSON batch thủ công) → `office_run`.
- **Giữ `office_read`** (đọc nhanh, không cần viết code).
- **Giữ `office_build`** giai đoạn này. Đánh giá lại sau eval: có thể đưa `parse_deck` vào module thành `office.build(src)`.

## 5. Các bước làm

1. **Module `office`** `packages/simp_agent/src/simp_agent/plugins/office_rt/office.py` (file đơn, stdlib).
   - Test unit với officecli giả (script ghi lại argv) → kiểm tra args, hàng đợi, flush trước đọc, map lỗi về dòng.
   - Test tích hợp với officecli thật (skip nếu không có): mỗi hàng ở mục 2 một test trên pptx/docx/xlsx mẫu.
2. **Tool `office_run`** trong `office.py`: ghi script, chạy, đọc sidecar, check, nạp ảnh. Test với `testing` env giả.
3. **Bỏ `office_edit`**, cập nhật mô tả `office_read` (bỏ nhắc `office_edit`), sửa test.
4. **Sandbox:** copy module vào `/opt/simp/py/` + `PYTHONPATH` trong `RUN_ENV`; E2B template (`e2b_template.py`) và Docker local. Kiểm tra Chromium/renderer cho `view screenshot` có trong image (nếu không: cài, hoặc fallback `soffice --convert-to pdf` + `pdftoppm`).
5. **Skill `pptx`/`docx`/`xlsx`:** thêm mục "sửa file bằng office_run" + ví dụ (vòng lặp, query rồi sửa, screenshot tự kiểm).
6. **Eval:** 3 việc (deck 8 slide; thêm 10 dòng bảng; sửa chữ hàng loạt trong docx của user; thêm công thức + định dạng xlsx). So cũ/mới: số lượt tool, token, thời gian, file hợp lệ.
7. Nhánh `office-code-mode` → PR → release notes.

## 6. Rủi ro
- `view screenshot` trên Linux dùng render HTML (không phải PowerPoint thật) → ảnh gần đúng; ghi chú trong mô tả tool.
- Resident officecli giữ khóa file: `atexit` luôn `close`; plugin `close` thêm lần nữa sau khi chạy (như `_build` đang làm).
- Batch lỗi giữa chừng: đã hỏi "all or none"? → test xác nhận hành vi thật của officecli, rồi ghi vào mô tả.
- Model không có vision → bỏ ảnh, chỉ trả `issues`.
