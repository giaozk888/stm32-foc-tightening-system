"""Generate the pinned official raw RPC interface; requires grpcio-tools.

Only generated files are written. No device, serial port or network is used.
"""
from pathlib import Path
import sys
import tempfile
import types

from grpc_tools import protoc
from google.protobuf import descriptor_pb2

root = Path(__file__).resolve().parents[1]
pw = root / "third_party/pigweed"
with tempfile.TemporaryDirectory(prefix="transfer-codegen-") as temporary:
    output = Path(temporary)
    import grpc_tools
    includes = [f"-I{pw}", f"-I{pw / 'pw_protobuf'}",
                f"-I{Path(grpc_tools.__file__).parent / '_proto'}"]
    status = protoc.main(["protoc", *includes, f"--python_out={output}",
                          "pw_protobuf_codegen_protos/codegen_options.proto",
                          "pw_protobuf_protos/field_options.proto"])
    if status:
        raise RuntimeError(f"Option protobuf generation failed: {status}")
    descriptor = output / "transfer.pb"
    status = protoc.main(["protoc", *includes, f"--descriptor_set_out={descriptor}",
                          "pw_transfer/transfer.proto"])
    if status:
        raise RuntimeError(f"Transfer descriptor generation failed: {status}")
    sys.path.insert(0, str(output))
    sys.path.insert(0, str(pw / "pw_protobuf/py"))
    # Load codegen without the runtime RPC client's optional generated imports.
    package = types.ModuleType("pw_rpc")
    package.__path__ = [str(pw / "pw_rpc/py/pw_rpc")]
    sys.modules["pw_rpc"] = package
    from pw_rpc.codegen_raw import process_proto_file
    from pw_protobuf import codegen_pwpb
    proto_set = descriptor_pb2.FileDescriptorSet.FromString(descriptor.read_bytes())
    files = list(process_proto_file(proto_set.file[0]))
    files.extend(codegen_pwpb.process_proto_file(
        proto_set.file[0], [], codegen_pwpb.GeneratorOptions(
            oneof_callbacks=True, exclude_legacy_snake_case_field_name_enums=False,
            suppress_legacy_namespace=False)))
    for generated in files:
        target = root / "firmware_common/generated" / generated.name()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.content(), encoding="utf-8", newline="\n")
        print(target.relative_to(root))
