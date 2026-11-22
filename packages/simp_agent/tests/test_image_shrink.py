import base64
import io
import os

import pytest
from PIL import Image

from simp_agent.agent.env import LocalEnv
from simp_agent.coding import tools


def noisy_png(path, w=3000, h=2200):
    """Random pixels: PNG can't compress them, so the file is far over 5 MB."""
    Image.frombytes("RGBA", (w, h), os.urandom(w * h * 4)).save(path)


async def test_big_picture_is_shrunk_to_a_jpeg(tmp_path):
    noisy_png(tmp_path / "big.png")
    assert (tmp_path / "big.png").stat().st_size > tools.MAX_IMAGE_BYTES
    url = await tools.load_image(LocalEnv(str(tmp_path)), "big.png")
    assert url.startswith("data:image/jpeg;base64,")
    data = base64.b64decode(url.split(",", 1)[1])
    assert len(data) <= tools.MAX_IMAGE_BYTES
    assert max(Image.open(io.BytesIO(data)).size) <= tools.MAX_IMAGE_SIDE


async def test_small_picture_kept_as_is(tmp_path):
    Image.new("RGB", (40, 30), "red").save(tmp_path / "s.png")
    url = await tools.load_image(LocalEnv(str(tmp_path)), "s.png")
    assert url == "data:image/png;base64," + base64.b64encode((tmp_path / "s.png").read_bytes()).decode()


async def test_without_pillow_big_picture_still_refused(tmp_path, monkeypatch):
    noisy_png(tmp_path / "big.png")
    monkeypatch.setattr(tools, "shrink_image", lambda data: None)
    with pytest.raises(ValueError, match="can't be viewed"):
        await tools.load_image(LocalEnv(str(tmp_path)), "big.png")
