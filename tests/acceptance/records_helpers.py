"""Shared M06 helpers for record acceptance tests (registered in spec/traceability.yaml)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = (ROOT / "fixtures/records/synthetic-sample-record-01.pdf").read_bytes()
UNREADABLE = (ROOT / "fixtures/records/synthetic-unreadable-record.pdf").read_bytes()
# #466: a structurally valid 1x1 PNG (intact chunks and CRCs, one IDAT); the earlier constant had a broken IDAT chunk.
PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
           b"\x00\x00\x00\x0bIDATx\xdac`\x00\x02\x00\x00\x05\x00\x01\xe9\xfa\xdc\xd8\x00\x00\x00\x00IEND\xaeB`\x82")


def png_chunk(kind: bytes, body: bytes, crc: int | None = None) -> bytes:
    import struct
    import zlib
    crc = zlib.crc32(kind + body) if crc is None else crc
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def png(width: int, height: int, *, idat: bool = True, ihdr_crc: int | None = None) -> bytes:
    """A synthetic PNG with this IHDR size (test-only). The image data is the 1x1 stream; upload validation checks the
    chunk structure, sizes and CRCs and never decodes it."""
    import struct
    head = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0), ihdr_crc)
    data = png_chunk(b"IDAT", b"x\xdac`\x00\x02\x00\x00\x05\x00\x01") if idat else b""
    return head + data + png_chunk(b"IEND", b"")


def upload(api, case_id: str, data: bytes, media_type: str = "application/pdf", name: str = "record.pdf",
           revision: int | None = None):
    rev = revision if revision is not None else api.case(case_id)["case"]["revision"]
    return api.req("POST", f"/cases/{case_id}/records", key=True, files={"file": (name, data, media_type)},
                   data={"expected_revision": str(rev)})


def upload_ok(api, case_id: str, data: bytes = SAMPLE, **kw) -> dict:
    r = upload(api, case_id, data, **kw)
    assert r.status_code == 202, r.text
    from conftest import validate
    validate("UploadRecordResponse", r.json())
    assert r.json()["document"]["status"] == "queued"
    return api.wait_job(r.json()["job_id"])


def records(api, case_id: str) -> dict:
    return api.ok("GET", f"/cases/{case_id}/records", 200, "RecordList")


def record_files(app) -> list[Path]:
    d = app[0].state.ctx.settings.data_dir / "records"
    return sorted(p for p in d.iterdir()) if d.exists() else []


def synthetic_pdf(tag: str, pages: int = 1) -> bytes:
    """A distinct, structurally valid synthetic PDF (test-only): the bundled sample plus a comment and pages."""
    head, rest = SAMPLE.split(b"\n", 1)
    return head + f"\n%test-sample {tag}\n".encode() + rest + b"<< /Type /Page >>\n" * (pages - 1) + b"%%EOF\n"


def scripted_app(tmp_path, samples: dict[str, tuple[bytes, list[dict]]]):
    """An app on a copy of the fixture pack with extra test-only scripted record samples.

    `samples` maps a fixture ID to (file bytes, scripted facts). The bundled fixtures are not changed.
    """
    import hashlib
    import json
    import shutil
    from dataclasses import replace

    from app.config import load_settings
    from app.main import create_app
    pack = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", pack)
    manifest = json.loads((pack / "records/manifest.json").read_text())
    profiles = json.loads((pack / "profiles.json").read_text())
    for fixture_id, (data, facts) in samples.items():
        (pack / "records" / f"{fixture_id}.pdf").write_bytes(data)
        manifest["samples"].append({"fixture_id": fixture_id, "file": f"{fixture_id}.pdf",
                                    "sha256": hashlib.sha256(data).hexdigest()})
        profiles["record_samples"].append({"fixture_id": fixture_id, "display_name": f"{fixture_id}.pdf",
                                           "sample_only": True, "real_file_provided": False, "ocr_executed": False,
                                           "facts": facts})
    (pack / "records/manifest.json").write_text(json.dumps(manifest))
    (pack / "profiles.json").write_text(json.dumps(profiles))
    return create_app(replace(load_settings(), data_dir=tmp_path / "data", fixtures_dir=pack))
