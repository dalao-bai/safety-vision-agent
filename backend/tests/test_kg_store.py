from app.kg.store import KGStore


def test_load_and_get_object(kg_path):
    kg = KGStore.load(str(kg_path))
    obj = kg.get_object("foundation_pit_edge_protection")
    assert obj is not None
    assert obj["name"] == "基坑临边防护"
    assert isinstance(obj.get("qualified_conditions"), list)


def test_object_by_name(kg_path):
    kg = KGStore.load(str(kg_path))
    assert kg.object_id_for_name("基坑临边防护") == "foundation_pit_edge_protection"


def test_get_hazard_type(kg_path):
    kg = KGStore.load(str(kg_path))
    ht = kg.get_hazard_type("missing_protection")
    assert ht is not None and ht.get("name") == "防护缺失"


def test_remediation_for_populated_object(kg_path):
    # stair_opening_protection has qualified_conditions in the KG
    kg = KGStore.load(str(kg_path))
    items = kg.remediation_for("stair_opening_protection")
    assert len(items) >= 1
    assert "condition" in items[0] and "source" in items[0]


def test_remediation_empty_when_no_qualified_conditions(kg_path):
    # foundation_pit has NO qualified_conditions in the KG (rules live in rule_blocks)
    kg = KGStore.load(str(kg_path))
    assert kg.remediation_for("foundation_pit_edge_protection") == []


def test_unknown_ids_return_none_or_empty(kg_path):
    kg = KGStore.load(str(kg_path))
    assert kg.get_object("nope") is None
    assert kg.get_hazard_type("nope") is None
    assert kg.remediation_for("nope") == []
