"""Setup script that generates Python protos at install time."""

import subprocess
import sys
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildProtos(build_py):
    """Custom build command that generates protos before building."""

    def run(self):
        # Generate protos into python/ directory
        proto_root = Path(__file__).parent
        python_out = proto_root / "python"
        python_out.mkdir(exist_ok=True)

        # Find all proto files
        protos = list(proto_root.glob("quantum/**/*.proto"))

        if protos:
            # Generate Python code using grpc_tools
            from grpc_tools import protoc

            for proto in protos:
                # Create output directory structure
                rel_path = proto.relative_to(proto_root)
                out_dir = python_out / rel_path.parent
                out_dir.mkdir(parents=True, exist_ok=True)

                # Create __init__.py files
                for parent in rel_path.parents:
                    if parent != Path("."):
                        init_file = python_out / parent / "__init__.py"
                        init_file.touch(exist_ok=True)

            # Run protoc
            protoc_args = [
                "grpc_tools.protoc",
                f"--proto_path={proto_root}",
                f"--python_out={python_out}",
                f"--grpc_python_out={python_out}",
                f"--pyi_out={python_out}",
            ] + [str(p) for p in protos]

            if protoc.main(protoc_args) != 0:
                raise RuntimeError("Proto generation failed")

            # Create py.typed marker
            (python_out / "py.typed").touch()

        # Continue with normal build
        super().run()


setup(cmdclass={"build_py": BuildProtos})
