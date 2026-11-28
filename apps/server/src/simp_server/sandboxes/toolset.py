"""The fixed toolset baked into the sandbox template (apps/server/sandboxes/e2b_template.py) and named in the prompt.
Users and the agent can use it but not change it: it lives in root-owned /opt/simp and the sandbox has no route to
package indexes. Add a library here, rebuild the template."""

PIP = ["pandas", "numpy", "matplotlib", "openpyxl", "python-docx", "python-pptx", "pypdf", "pdfplumber", "reportlab",
       "lxml", "pillow", "requests", "beautifulsoup4", "defusedxml", "markitdown", "pdf2image", "pytesseract"]
APT = ["git", "ripgrep", "fd-find", "zstd", "s3fs", "ffmpeg", "imagemagick", "procps", "util-linux", "curl",
       "ca-certificates", "nodejs", "tesseract-ocr", "tesseract-ocr-vie", "tesseract-ocr-eng", "fonts-noto-core",
       "fonts-dejavu-core", "fonts-crosextra-carlito", "fonts-crosextra-caladea", "npm", "pandoc", "poppler-utils", "qpdf"]
# headless browser: officecli renders slides/pages/sheets to HTML and screenshots them with it
OFFICE_APT = ["chromium"]
# node libraries the office skills (apps/server/skill_library) use, installed under NODE_DIR and found through NODE_PATH
# + artwork for slides and documents (MIT): flat illustrations and line icons as Iconify JSON, used by office.art()
NPM = ["pptxgenjs", "docx", "react", "react-dom", "react-icons", "sharp", "@iconify-json/fluent-emoji-flat", "@iconify-json/tabler"]
NODE_DIR = "/opt/simp/node"
# officecli (github.com/iOfficeAI/OfficeCLI, Rust): builds and checks .pptx/.docx/.xlsx for the office_* tools
OFFICECLI = ("v1.0.162", {"x86_64": "df40e8f21b5c84826565f7c9c96f7e1a70ffbfe141b507bdad70533eaeacc190",
                          "aarch64": "59763bc3e9f03784fb4ddb7a2571deabaaf5fb999f42aaee6407191424c38816"})


def officecli_install() -> str:
    """Shell for the template: the binary for this machine's arch, checked against its pinned sha256."""
    ver, sums = OFFICECLI
    url = f"https://github.com/iOfficeAI/OfficeCLI/releases/download/{ver}/officecli-linux-"
    return ("arch=$(uname -m) && case $arch in x86_64) f=x64 s=" + sums["x86_64"] + ";; aarch64) f=arm64 s=" + sums["aarch64"]
            + ";; *) echo unsupported arch $arch; exit 1;; esac && curl -fsSL -o /usr/local/bin/officecli " + url + "$f"
            + " && echo \"$s  /usr/local/bin/officecli\" | sha256sum -c - && chmod 755 /usr/local/bin/officecli")
SKILLS_DIR = "/opt/simp/skills"  # the user's own skills, written there (read-only for the agent) by user_skills.py
# office_build's house style for .docx, baked into the template (from the library's docx skill)
OFFICE_DIR = "/opt/simp/office"
OFFICE_REFERENCE_DOCX = f"{OFFICE_DIR}/reference.docx"


def prompt_list(office: bool) -> str:
    cli = "ffmpeg, imagemagick, tesseract OCR (vie, eng), git, node, officecli" + (", chromium (headless)" if office else "")
    return (f"Preinstalled Python libraries: {', '.join(PIP)}. Node libraries (require directly): {', '.join(NPM)}. "
            f"Command-line tools: {cli}, pandoc, pdftoppm, qpdf.")


VENV = "/opt/simp/venv"
# E2B applies template envs only at build time, so E2BSandbox exports these in every command.
RUN_ENV = {"PYTHONNOUSERSITE": "1", "NODE_PATH": f"{NODE_DIR}/node_modules",
           "PATH": f"{VENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}


APP = __import__("pathlib").Path(__file__).parents[3]  # apps/server
TEMPLATE_INPUTS = ["sandboxes/e2b_template.py", "sandboxes/chromium.sh", "src/simp_server/sandboxes/toolset.py",
                   "sandboxes/reference.docx"]


def template_alias(office: bool = True) -> str:
    """E2B template name from a hash of everything baked into it. The release workflow builds it when missing and
    the server computes the same name, so a toolset or skills change never needs a settings edit."""
    import hashlib
    h = hashlib.sha256(b"office" if office else b"")
    for rel in TEMPLATE_INPUTS:
        root = APP / rel
        for f in sorted([root] if root.is_file() else (x for x in root.rglob("*") if x.is_file() and "__pycache__" not in x.parts)):
            h.update(str(f.relative_to(APP)).encode() + b"\0" + f.read_bytes())
    return f"simp-sandbox-{h.hexdigest()[:12]}"
