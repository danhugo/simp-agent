"""The fixed toolset baked into the sandbox template (apps/server/sandboxes/e2b_template.py) and named in the prompt.
Users and the agent can use it but not change it: it lives in root-owned /opt/simp and the sandbox has no route to
package indexes. Add a library here, rebuild the template."""

PIP = ["pandas", "numpy", "matplotlib", "openpyxl", "python-docx", "python-pptx", "pypdf", "pdfplumber", "reportlab",
       "lxml", "pillow", "requests", "beautifulsoup4", "defusedxml", "markitdown", "pdf2image", "pytesseract"]
APT = ["git", "ripgrep", "fd-find", "zstd", "s3fs", "ffmpeg", "imagemagick", "procps", "util-linux", "curl",
       "ca-certificates", "nodejs", "tesseract-ocr", "tesseract-ocr-vie", "tesseract-ocr-eng", "fonts-noto-core",
       "fonts-dejavu-core", "npm", "pandoc", "poppler-utils", "qpdf"]
OFFICE_APT = ["libreoffice-nogui"]
# node libraries the skills (apps/server/skills) use, installed under NODE_DIR and found through NODE_PATH
NPM = ["pptxgenjs", "docx", "react", "react-dom", "react-icons", "sharp"]
NODE_DIR = "/opt/simp/node"
SKILLS_DIR = "/opt/simp/skills"  # apps/server/skills, copied read-only into the template


def prompt_list(office: bool) -> str:
    cli = "ffmpeg, imagemagick, tesseract OCR (vie, eng), git, node" + (", LibreOffice (soffice --headless)" if office else "")
    return (f"Preinstalled Python libraries: {', '.join(PIP)}. Node libraries (require directly): {', '.join(NPM)}. "
            f"Command-line tools: {cli}, pandoc, pdftoppm, qpdf.")


VENV = "/opt/simp/venv"
# E2B applies template envs only at build time, so E2BSandbox exports these in every command.
RUN_ENV = {"PYTHONNOUSERSITE": "1", "NODE_PATH": f"{NODE_DIR}/node_modules",
           "PATH": f"{VENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
