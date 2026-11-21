import hashlib
from pathlib import Path

from backend.app.domain import reference_toolchain_qualification as qualification


def test_reference_qualification_uses_configured_bcftools_path_and_indexed_fasta_reader(tmp_path, monkeypatch):
    fasta = tmp_path / "reference.fa"
    fasta.write_bytes(b">chr1\nGCAAAAACG\n")
    Path(f"{fasta}.fai").write_bytes(b"chr1\t9\t6\t9\t10\n")
    bcftools = tmp_path / "profile" / "bin" / "bcftools"
    bcftools.parent.mkdir(parents=True)
    bcftools.write_bytes(b"configured bcftools executable")
    resolved = str(bcftools.resolve())
    commands = []

    def no_path_lookup(_name):
        raise AssertionError("configured executable paths must not depend on PATH")

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[0] == str(bcftools.resolve()) and command[1] == "--version":
            return {"command": command, "returncode": 0, "stdout": "bcftools 1.21\n", "stderr": ""}
        if command[0] == str(bcftools.resolve()) and command[1] == "norm":
            if "incorrect-ref.vcf" in command[-1]:
                return {
                    "command": command,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": "Reference allele mismatch",
                }
            output = Path(command[command.index("-o") + 1])
            output.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "chr1\t3\t.\tA\tAA\t.\tPASS\t.\n"
                "chr1\t1\t.\tG\tA\t.\tPASS\t.\n",
                encoding="ascii",
            )
            return {"command": command, "returncode": 0, "stdout": "", "stderr": ""}
        raise AssertionError(f"unexpected qualification command: {command!r}")

    monkeypatch.setattr(qualification.shutil, "which", no_path_lookup)
    monkeypatch.setattr(qualification, "_run", fake_run)
    result = qualification.execute_bcftools_reference_check(
        fasta,
        [{"name": "chr1", "length": 9}],
        expected_fasta_sha256=hashlib.sha256(fasta.read_bytes()).hexdigest(),
        expected_bcftools_version="1.21",
        bcftools_executable=str(bcftools),
    )

    assert result["status"] == "VERIFIED", result
    assert result["bcftools_executable"] == str(bcftools.resolve())
    assert result["reference_sequence_reader"] == "siraloom-fasta-index-reader-v1"
    assert {command[0] for command in commands} == {resolved}
