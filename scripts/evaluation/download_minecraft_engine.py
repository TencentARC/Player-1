"""Download and extract the upstream MineStudio engine into a new directory."""

import stat
import zipfile
from pathlib import Path

ENGINE_REPOSITORY = "CraftJarvis/SimulatorEngine"
OUTPUT = Path("downloads/minecraft-runtime")


def extract(archive_path, output):
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise ValueError("Choose a new engine directory; existing assets are preserved")
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            destination = (output / member.filename).resolve()
            if not destination.is_relative_to(output) or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Unsafe engine archive member: {member.filename}")
        output.mkdir(parents=True)
        archive.extractall(output)
    jar = output / "engine/build/libs/mcprec-6.13.jar"
    if not zipfile.is_zipfile(jar):
        raise ValueError(f"Engine archive is missing a readable JAR: {jar}")
    for script in (output / "engine").rglob("*.sh"):
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return jar


def download(output: Path):
    if output.expanduser().exists():
        raise ValueError("Choose a new engine directory; existing assets are preserved")
    from huggingface_hub import hf_hub_download
    archive = hf_hub_download(ENGINE_REPOSITORY, "engine.zip")
    jar = extract(archive, output)
    print(f"Original engine: {jar}")
    return jar


if __name__ == "__main__":
    download(OUTPUT)
