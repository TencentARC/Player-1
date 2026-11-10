"""Local simulator extraction and portable engine archive checks."""

import io
import stat
import zipfile

import pytest

from scripts.evaluation.download_minecraft_engine import extract
from scripts.evaluation.prepare_minecraft_runtime import prepare


def test_engine_extraction_accepts_a_valid_jar_and_preserves_existing_outputs(tmp_path):
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    source = tmp_path / "engine.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("engine/build/libs/mcprec-6.13.jar", jar.getvalue())
        archive.writestr("engine/launch.sh", "#!/bin/sh\n")
    output = tmp_path / "runtime"
    assert extract(source, output).read_bytes() == jar.getvalue()
    assert (output / "engine/launch.sh").stat().st_mode & stat.S_IXUSR
    with pytest.raises(ValueError, match="new engine directory"):
        extract(source, output)


@pytest.mark.parametrize("name,mode", [("../outside", 0), ("/outside", 0), ("engine/link", stat.S_IFLNK)])
def test_engine_extraction_rejects_unsafe_members_before_writing(tmp_path, name, mode):
    source = tmp_path / "engine.zip"
    member = zipfile.ZipInfo(name)
    member.external_attr = mode << 16
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(member, "outside")
    output = tmp_path / "runtime"
    with pytest.raises(ValueError, match="Unsafe engine archive member"):
        extract(source, output)
    assert not output.exists()


@pytest.mark.parametrize("contents", [None, b"invalid jar"])
def test_engine_extraction_requires_a_readable_jar(tmp_path, contents):
    source = tmp_path / "engine.zip"
    with zipfile.ZipFile(source, "w") as archive:
        if contents is not None:
            archive.writestr("engine/build/libs/mcprec-6.13.jar", contents)
    with pytest.raises(ValueError, match="missing a readable JAR"):
        extract(source, tmp_path / "runtime")


def test_prepare_runtime_from_local_sources_with_licenses(tmp_path):
    source = tmp_path / "source"
    files = {
        "minestudio/simulator/minerl/runtime.py": "# simulator\n",
        "minestudio/simulator/minerl/Malmo/Schemas/task.xsd": "schema",
        "minestudio/simulator/minerl/Malmo/LICENSE.txt": "Malmo license",
        "minestudio/simulator/minerl/Malmo/native.so": "native binary",
        "minestudio/utils/temp.py": "# temp\n",
        "minestudio/utils/register.py": "# register\n",
        "LICENSE": "MineStudio license",
    }
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    output = tmp_path / "runtime"
    prepare(source, output)
    for name in files.keys() - {"minestudio/simulator/minerl/Malmo/native.so"}:
        assert (output / name).read_text() == files[name]
    assert not (output / "minestudio/simulator/minerl/Malmo/native.so").exists()
    assert (source / "minestudio/simulator/minerl/Malmo/native.so").read_text() == "native binary"
    with pytest.raises(ValueError, match="new output directory"):
        prepare(source, output)
