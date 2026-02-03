"""Setup script that generates Python protos at install time."""

import subprocess
import sys
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info


def generate_protos():
    """Generate Python proto stubs."""
    proto_root = Path(__file__).parent
    python_out = proto_root / "python"
    python_out.mkdir(exist_ok=True)

    # Find all proto files
    protos = list(proto_root.glob("quantum/**/*.proto"))

    if not protos:
        print("No proto files found, skipping generation")
        return

    try:
        from grpc_tools import protoc
    except ImportError:
        print("grpc_tools not available, skipping proto generation")
        return

    # Create output directory structure and __init__.py files
    for proto in protos:
        rel_path = proto.relative_to(proto_root)
        out_dir = python_out / rel_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        # Create __init__.py files for all parent directories
        for parent in rel_path.parents:
            if parent != Path("."):
                init_file = python_out / parent / "__init__.py"
                if not init_file.exists():
                    init_file.touch()

    # Run protoc for all protos
    protoc_args = [
        "grpc_tools.protoc",
        f"--proto_path={proto_root}",
        f"--python_out={python_out}",
        f"--grpc_python_out={python_out}",
        f"--pyi_out={python_out}",
    ] + [str(p) for p in protos]

    result = protoc.main(protoc_args)
    if result != 0:
        raise RuntimeError(f"Proto generation failed with code {result}")

    # Create py.typed marker
    (python_out / "py.typed").touch()
    print(f"Generated {len(protos)} proto files to {python_out}")


class BuildProtos(build_py):
    """Custom build command that generates protos before building."""

    def run(self):
        generate_protos()
        super().run()


class EggInfoProtos(egg_info):
    """Custom egg_info that generates protos first."""

    def run(self):
        generate_protos()
        super().run()


setup(
    cmdclass={
        "build_py": BuildProtos,
        "egg_info": EggInfoProtos,
    }
)
