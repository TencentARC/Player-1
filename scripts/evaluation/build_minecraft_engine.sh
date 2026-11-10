#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 2 ]]; then
  printf 'Usage: JAVA_HOME=/path/to/jdk8 bash scripts/evaluation/build_minecraft_engine.sh INPUT_JAR OUTPUT_JAR\n' >&2
  exit 2
fi
java_home="${JAVA_HOME:?Set JAVA_HOME to a Java 8 JDK}"
source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source_directory="$source_root/player1/environments/minestudio/engine_patches"
input_jar="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' "$1")"
output_jar="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$2")"
if [[ "$input_jar" == "$output_jar" || -e "$output_jar" ]]; then
  printf 'Choose a new output path; the input and existing output are preserved.\n' >&2
  exit 2
fi
work_directory="$(mktemp -d)"
trap 'rm -rf "$work_directory"' EXIT
mkdir -p "$(dirname "$output_jar")" "$work_directory/classes"
"$java_home/bin/javac" -source 8 -target 8 -cp "$input_jar" -d "$work_directory/classes" \
  "$source_directory/PatchMineStudioEngine.java" "$source_directory/PlayerOneWorldReset.java" \
  "$source_directory/PlayerOneInputBridge.java" "$source_directory/VerifyMineStudioEngine.java"
"$java_home/bin/java" -cp "$input_jar:$work_directory/classes" PatchMineStudioEngine \
  "$input_jar" "$work_directory/patched.jar"
"$java_home/bin/java" -Xverify:all -cp "$work_directory/patched.jar:$work_directory/classes" VerifyMineStudioEngine
cp "$work_directory/patched.jar" "$output_jar"
printf '%s\n' "$output_jar"
