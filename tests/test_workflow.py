from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from tests.test_excel import mapping, template
from tests.test_extraction import block
from tests.test_records import verified_fields


class PrintedLabelEngine:
    """Only the expensive external model is replaced in HTTP workflow tests."""

    def recognize(self, asset):
        return [
            block(text, n, asset.id)
            for n, text in enumerate(
                [
                    "产品名称：复配稳定剂",
                    "规格：25kg/袋",
                    "生产厂商：青山食品有限公司",
                    "生产地址：浙江省杭州市测试路1号",
                    "批号：00123",
                    "生产日期：2026年10月1日",
                    "保质期：12个月",
                ]
            )
        ]


def test_local_workflow_import_review_confirm_reopen_export(tmp_path):
    from app.main import create_app

    picture = BytesIO()
    Image.new("RGB", (600, 300), "white").save(picture, format="PNG")
    app = create_app(tmp_path / "data", engine=PrintedLabelEngine())
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        imported = client.post(
            "/api/images", files=[("files", ("label.png", picture.getvalue(), "image/png"))]
        )
        assert imported.status_code == 200
        image_id = imported.json()["images"][0]["id"]
        app.state.ocr.close()
        assert client.get(f"/api/images/{image_id}/file").headers["content-type"] == "image/png"
        grouped = client.post("/api/receipts", json={"image_ids": [image_id]})
        assert grouped.status_code == 200
        receipt = grouped.json()
        candidates = client.get(f"/api/receipts/{receipt['id']}/candidates").json()
        assert candidates["lot"][0]["value"] == "00123"
        confirmed = client.post(
            f"/api/receipts/{receipt['id']}/confirm",
            json={
                "fields": verified_fields(),
                "operator": "王检验",
                "expected_version": 0,
                "grouping_reviewed": True,
                "product_decision": {"mode": "new"},
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["record"]["fields"]["lot"]["value"] == "00123"
        source = template(tmp_path)
        uploaded = client.post("/api/template", files={"file": (source.name, source.read_bytes())})
        assert uploaded.json()["sheets"] == ["来料"]
        assert client.put("/api/template/config", json=mapping()).status_code == 200
        exported = client.post("/api/exports", json={})
        assert exported.status_code == 200
        assert exported.json()["count"] == 1
        downloaded = client.get(exported.json()["url"])
        from openpyxl import load_workbook

        assert load_workbook(BytesIO(downloaded.content)).active["E2"].value == "00123"
    with TestClient(create_app(tmp_path / "data", engine=PrintedLabelEngine())) as restarted:
        state = restarted.get("/api/state").json()
        assert state["receipts"][0]["confirmed"]["operator"] == "王检验"
        assert state["operator"] == "王检验"


def test_review_endpoints_support_suggestions_drafts_photo_moves_and_ocr_samples(tmp_path):
    from app.images import ImageStore
    from app.main import create_app
    from tests.test_records import make_image

    root = tmp_path / "data"
    images = ImageStore(root)
    ids = [make_image(root), make_image(root)]
    for identifier in ids:
        asset = images.get(identifier)
        asset.blocks = PrintedLabelEngine().recognize(asset)
        asset.status = "done"
        images.save(asset)
    with TestClient(create_app(root, engine=PrintedLabelEngine())) as client:
        suggested = client.post("/api/groups/suggest", json={"image_ids": ids})
        assert suggested.status_code == 200
        assert suggested.json()["groups"][0]["image_ids"] == ids
        source = client.post("/api/receipts", json={"image_ids": [ids[0]]}).json()
        target = client.post("/api/receipts", json={"image_ids": [ids[1]]}).json()
        saved = client.put(
            f"/api/receipts/{source['id']}",
            json={
                "fields": verified_fields(),
                "operator": "王检验",
                "reason": "初次录入",
                "expected_version": 0,
            },
        )
        assert saved.status_code == 200
        moved = client.post(
            f"/api/images/{ids[1]}/move",
            json={
                "target_id": source["id"],
                "operator": "王检验",
                "reason": "核实为同一袋包装的背面",
                "expected_versions": {source["id"]: 1, target["id"]: 0},
            },
        )
        assert moved.status_code == 200
        fields = verified_fields()
        fields["lot"] = {"raw": "00123", "value": "00124", "source": "image", "refs": [f"{ids[0]}:4"]}
        confirmed = client.post(
            f"/api/receipts/{source['id']}/confirm",
            json={
                "fields": fields,
                "operator": "王检验",
                "expected_version": 2,
                "grouping_reviewed": True,
                "region_labels": {f"{ids[0]}:4": "批号：00124"},
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["samples"]["count"] == 1
        sample_id = client.get("/api/state").json()["samples"][0]["id"]
        crop_response = client.get(f"/api/samples/{sample_id}/file")
        assert crop_response.status_code == 200
        with Image.open(BytesIO(crop_response.content)) as crop:
            assert crop.width == 400
        suggestions = client.post("/api/products/suggest", json={"name": "复配稳定剂"})
        assert suggestions.json()[0]["current"]["name"] == "复配稳定剂"


def test_separate_import_batches_never_automatically_become_one_arrival(tmp_path):
    from app.main import create_app

    root = tmp_path / "data"
    app = create_app(root, engine=PrintedLabelEngine())
    buffer = BytesIO()
    Image.new("RGB", (600, 300), "white").save(buffer, format="PNG")
    with TestClient(app) as client:
        image_ids = []
        for _ in range(2):
            response = client.post("/api/images", files=[("files", ("same.png", buffer.getvalue()))])
            image_ids.append(response.json()["images"][0]["id"])
        app.state.ocr.close()
        proposed = client.post("/api/groups/suggest", json={"image_ids": image_ids}).json()
        assert len(proposed["groups"]) == 2
        assert [group["image_ids"] for group in proposed["groups"]] == [[image_ids[0]], [image_ids[1]]]


def test_local_api_rejects_cross_origin_writes(tmp_path):
    from app.main import create_app

    with TestClient(create_app(tmp_path, engine=PrintedLabelEngine())) as client:
        response = client.post(
            "/api/receipts", json={"image_ids": []}, headers={"Origin": "https://unrelated.example"}
        )
        assert response.status_code == 403
        assert client.get("/api/state").json()["receipts"] == []


def test_saving_draft_preserves_pending_product_choice_and_region_corrections(tmp_path):
    from app.main import create_app
    from tests.test_records import make_image

    root = tmp_path / "data"
    image_id = make_image(root)
    with TestClient(create_app(root, engine=PrintedLabelEngine())) as client:
        receipt = client.post("/api/receipts", json={"image_ids": [image_id]}).json()
        saved = client.put(
            f"/api/receipts/{receipt['id']}",
            json={
                "fields": verified_fields(),
                "operator": "王检验",
                "reason": "继续核对",
                "expected_version": 0,
                "grouping_reviewed": True,
                "region_labels": {f"{image_id}:0": "产品名称：复配稳定剂"},
                "product_decision": {"mode": "new"},
            },
        )
        assert saved.status_code == 200
        draft = client.get("/api/state").json()["receipts"][0]["draft"]
        assert draft["region_labels"] == {f"{image_id}:0": "产品名称：复配稳定剂"}
        assert draft["product_decision"] == {"mode": "new"}
        assert draft["grouping_reviewed"] is True
