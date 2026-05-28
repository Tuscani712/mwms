"""Recipe name field + DELETE endpoint (SCO-142).

Covers:
- POST /production/recipes accepts an optional `name` and persists it.
- GET /production/recipes returns `name` in payloads; blank falls back
  to "Recipe #{id}" so the UI never shows an empty label.
- DELETE /production/recipes/{id} → 204 on clean delete; cascades the
  RecipeLine rows.
- DELETE returns 409 with the WO count in the detail when any WorkOrder
  references the recipe.
- DELETE returns 404 for an unknown recipe id.
- Audit event `recipe.deleted` recorded with the pre-delete snapshot.
"""

from wms.models import AuditLog, Recipe, RecipeLine, WorkOrder


def _create_recipe(client, headers, product_sku_id, ingredient_sku_id, *, name=""):
    return client.post(
        "/api/v1/production/recipes",
        json={
            "sku_id": product_sku_id,
            "name": name,
            "lines": [
                {"ingredient_sku_id": ingredient_sku_id, "qty_per_unit": 2, "uom": "KG"},
            ],
        },
        headers=headers,
    )


def test_recipe_name_persists_and_serializes(client, auth_headers, seeded_db):
    # Use seeded SKUs FLR-001 (id=1) + SGR-001 (id=2). Create a recipe
    # producing FLR-001 from SGR-001 — trivial but valid for this test.
    r = _create_recipe(client, auth_headers, 1, 2, name="House Bread")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "House Bread"
    assert body["sku_id"] == 1

    # GET also returns the name.
    lst = client.get("/api/v1/production/recipes", headers=auth_headers)
    assert lst.status_code == 200
    found = [row for row in lst.json() if row["id"] == body["id"]]
    assert found and found[0]["name"] == "House Bread"


def test_recipe_blank_name_falls_back_to_id(client, auth_headers, seeded_db):
    r = _create_recipe(client, auth_headers, 1, 2, name="")
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == f"Recipe #{body['id']}"


def test_delete_recipe_clean(client, auth_headers, seeded_db):
    db = seeded_db
    r = _create_recipe(client, auth_headers, 1, 2, name="Disposable")
    recipe_id = r.json()["id"]

    # Confirm row + line exist.
    assert db.get(Recipe, recipe_id) is not None
    assert db.query(RecipeLine).filter(RecipeLine.recipe_id == recipe_id).count() == 1

    # DELETE → 204.
    d = client.delete(f"/api/v1/production/recipes/{recipe_id}", headers=auth_headers)
    assert d.status_code == 204, d.text

    # Row + cascade.
    db.expire_all()
    assert db.get(Recipe, recipe_id) is None
    assert db.query(RecipeLine).filter(RecipeLine.recipe_id == recipe_id).count() == 0

    # Audit event with snapshot.
    events = (
        db.query(AuditLog)
        .filter(AuditLog.event_type == "recipe.deleted")
        .order_by(AuditLog.id.desc())
        .all()
    )
    assert events, "expected a recipe.deleted audit event"
    detail = events[0].detail_json or ""
    assert '"name": "Disposable"' in detail
    assert f'"id": {recipe_id}' in detail


def test_delete_recipe_in_use_returns_409(client, auth_headers, seeded_db):
    db = seeded_db
    r = _create_recipe(client, auth_headers, 1, 2, name="LockedByWO")
    recipe_id = r.json()["id"]

    # Attach a WorkOrder so the FK-safe guard fires.
    wo = WorkOrder(
        recipe_id=recipe_id,
        recipe_version_snapshot=1,
        target_qty=10,
        status="draft",
        site_id="WHS-001",
    )
    db.add(wo)
    db.commit()

    d = client.delete(f"/api/v1/production/recipes/{recipe_id}", headers=auth_headers)
    assert d.status_code == 409, d.text
    # Detail should call out the count.
    assert "1 work order" in d.json()["detail"]

    # Recipe still present — FK guard didn't half-commit.
    assert db.get(Recipe, recipe_id) is not None


def test_delete_recipe_404_for_missing(client, auth_headers, seeded_db):
    d = client.delete("/api/v1/production/recipes/999999", headers=auth_headers)
    assert d.status_code == 404, d.text
