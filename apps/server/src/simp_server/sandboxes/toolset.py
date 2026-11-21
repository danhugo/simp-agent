"""The fixed toolset baked into the sandbox template (apps/server/sandboxes/e2b_template.py) and named in the prompt.
Users and the agent can use it but not change it: it lives in root-owned /opt/simp and the sandbox has no route to
package indexes. Add a library here, rebuild the template."""

PIP = ["pandas", "numpy", "matplotlib", "openpyxl", "python-docx", "python-pptx", "pypdf", "pdfplumber", "reportlab",
       "lxml", "pillow", "requests", "beautifulsoup4"]
APT = ["git", "ripgrep", "fd-find", "zstd", "s3fs", "ffmpeg", "imagemagick", "procps", "util-linux", "curl",
       "ca-certificates", "nodejs", "tesseract-ocr", "tesseract-ocr-vie", "tesseract-ocr-eng", "fonts-noto-core",
       "fonts-dejavu-core"]
OFFICE_APT = ["libreoffice-nogui"]


def prompt_list(office: bool) -> str:
    cli = "ffmpeg, imagemagick, tesseract OCR (vie, eng), git, node" + (", LibreOffice (soffice --headless)" if office else "")
    return f"Preinstalled Python libraries: {', '.join(PIP)}. Command-line tools: {cli}."


VENV = "/opt/simp/venv"
# E2B applies template envs only at build time, so E2BSandbox exports these in every command.
RUN_ENV = {"PYTHONNOUSERSITE": "1",
           "PATH": f"{VENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
